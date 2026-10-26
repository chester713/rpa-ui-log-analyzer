"""CSV loader for UI log files."""

import csv
import json
import logging
import re
from typing import List, Dict, Any, Optional
from ..llm.client import LLMError
from ..models.event import Event

_logger = logging.getLogger(__name__)

# Execution environments, richest interface information first.
_ENVIRONMENTS = ("web", "desktop", "screen")


class CSVLoader:
    """Loads CSV files and uses LLM to detect event column."""

    def __init__(self, llm_client=None):
        self.llm_client = llm_client
        self._force_column = None
        self.detected_column = None
        self.llm_recommended = False
        self.detected_group_columns: Optional[List[str]] = None
        self.detected_switch_columns: Optional[List[str]] = None
        # environment -> columns indicating it ("web", "desktop", "screen")
        self.detected_environment_columns: Optional[Dict[str, List[str]]] = None
        # columns that identify the target UI element (element id, XPath, cell, ...)
        self.detected_element_columns: Optional[List[str]] = None

    @staticmethod
    def _dedup_headers(raw_headers: List[str]) -> List[str]:
        """Rename duplicate column names by appending .1, .2, etc.

        csv.DictReader silently overwrites earlier columns when names collide.
        This preserves every column's data by giving each occurrence a unique key.
        """
        seen: Dict[str, int] = {}
        result: List[str] = []
        for h in raw_headers:
            if h in seen:
                seen[h] += 1
                result.append(f"{h}.{seen[h]}")
            else:
                seen[h] = 0
                result.append(h)
        return result

    def load(self, filepath: str) -> List[Event]:
        """
        Load CSV file and return list of Event objects.

        Args:
            filepath: Path to CSV file

        Returns:
            List of Event objects

        Raises:
            ValueError: If event column cannot be detected or LLM is unavailable
            FileNotFoundError: If file doesn't exist
        """
        with open(filepath, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            raw_headers = next(reader, [])
            fieldnames = self._dedup_headers(raw_headers)
            rows = [
                {h: (values[j] if j < len(values) else "") for j, h in enumerate(fieldnames)}
                for values in reader
            ]

        if self._force_column:
            event_column = self._force_column
        else:
            event_column = self._detect_event_column_with_llm(
                fieldnames, sample_rows=rows[:50]
            )

        self.detected_column = event_column
        context_cols = self._detect_context_columns_with_llm(
            fieldnames, sample_rows=rows[:50], exclude=event_column
        )
        self.detected_group_columns = context_cols.get("group_columns") or None
        self.detected_switch_columns = context_cols.get("switch_columns") or None
        self.detected_environment_columns = context_cols.get("environment_columns")
        self.detected_element_columns = context_cols.get("element_columns") or None

        if event_column is None:
            raise ValueError(
                f"Missing required column: event (could not detect event column. Found columns: {fieldnames})"
            )

        events = []
        for row_index, row in enumerate(rows):
            event_name = row.get(event_column, "").strip()
            attributes = {k: v for k, v in row.items() if k != event_column and v}
            events.append(
                Event(event=event_name, attributes=attributes, row_index=row_index)
            )

        return events

    def _detect_event_column_with_llm(
        self, fieldnames: List[str], sample_rows: Optional[List[Dict[str, Any]]] = None
    ) -> Optional[str]:
        if self.llm_client is None:
            raise ValueError("LLM client required for event column detection")

        columns_str = ", ".join(fieldnames or [])
        sample_rows = sample_rows or []
        sample_by_column = []
        for field in fieldnames or []:
            values = []
            for row in sample_rows:
                val = str((row or {}).get(field, "")).strip()
                if val:
                    values.append(val)
                if len(values) >= 8:
                    break
            sample_by_column.append(f"- {field}: {values}")

        sample_str = "\n".join(sample_by_column)
        prompt = f"""You are selecting the activity-name attribute of a UI log (in the CSV file, each attribute is a column).

Attributes:
{columns_str}

Sample values per attribute:
{sample_str}

Choose the attribute whose values generally look like UI actions, usually verb+noun style labels.
Examples: activateWorkbook, openWindow, clickTextField, setValue, findElement.

Avoid attributes that are timestamps, ids, URLs, application names, free-text descriptions, or long sentences.

Return only one exact attribute name from the list above. No explanation."""

        response = self.llm_client.complete(prompt)
        detected = self._extract_detected_field(response, fieldnames)

        for field in fieldnames or []:
            field_name = (field or "").strip()
            if not field_name:
                continue
            if field_name.lower() == detected.lower():
                self.llm_recommended = True
                return field

        self.llm_recommended = False
        return None

    def _detect_context_columns_with_llm(
        self,
        fieldnames: List[str],
        sample_rows: Optional[List[Dict[str, Any]]] = None,
        exclude: Optional[str] = None,
    ) -> Dict[str, Any]:
        candidates = [f for f in (fieldnames or []) if f != exclude]
        if not candidates:
            return {
                "group_columns": [],
                "switch_columns": [],
                "environment_columns": {env: [] for env in _ENVIRONMENTS},
                "element_columns": [],
            }

        if self.llm_client is None:
            raise ValueError("LLM client required for context column detection")

        sample_by_column = []
        for field in candidates:
            values = []
            for row in (sample_rows or []):
                val = str((row or {}).get(field, "")).strip()
                if val:
                    values.append(val)
                if len(values) >= 5:
                    break
            sample_by_column.append(f"- {field}: {values}")

        sample_str = "\n".join(sample_by_column)
        prompt = f"""You are analysing the attributes of a UI log (in the CSV file, each attribute is a column).

Attributes (the activity-name attribute has already been identified and is excluded):
{", ".join(candidates)}

Sample values per attribute:
{sample_str}

Identify four attribute sets:
1. "switch_attributes": attributes whose value identifies which application or process is active (e.g. application name, process name). A change in this value means the user switched to a different application. Do not include window or page titles: they change when the user navigates within one application.
2. "group_attributes": attributes useful for grouping consecutive events into the same activity (includes switch_attributes plus things like URL, screen name, webpage, tab, element scope).
3. "environment_attributes": attributes whose recorded value shows the execution environment the event took place in. Classify by what the attribute describes, not by its name:
   - "web": properties of an HTML/DOM element or of a browser location (e.g. XPath, HTML tag, HTML id or name, page URL, webpage title).
   - "desktop": properties of a native application's user interface or document structure (e.g. application or process name, window title, workbook, worksheet, cell reference, UI Automation control type or path).
   - "screen": raw screen positions (e.g. x/y or mouse coordinates).
   An attribute belongs to at most one environment. Attributes that indicate none of them (timestamps, ids, case ids, typed values, clipboard content, free text) are left out.
4. "element_attributes": attributes whose value identifies the specific UI element an event targets (e.g. element id or name, XPath, cell reference, UI Automation id or control name), in order of preference. Attributes describing the page, window or application are not element attributes.

Rules:
- Only include attribute names that appear exactly in the list above.
- "switch_attributes" must be a subset of "group_attributes".
- Return empty lists if no attribute qualifies.
- Return only valid JSON, no explanation.

Format:
{{"switch_attributes": ["a1"], "group_attributes": ["a1", "a2"], "environment_attributes": {{"web": ["a2"], "desktop": ["a1"], "screen": []}}, "element_attributes": ["a3"]}}"""

        response = self.llm_client.complete(prompt)
        clean = (response or "").strip()
        if clean.startswith("```"):
            clean = re.sub(r"```[a-z]*\n?", "", clean).strip("`").strip()
        try:
            parsed = json.loads(clean)
        except json.JSONDecodeError as exc:
            raise LLMError(
                "The language model did not return valid JSON when identifying the roles of the "
                f"log's attributes ({exc.msg}). Please try again."
            ) from exc
        if not isinstance(parsed, dict):
            raise LLMError(
                "The language model returned an unexpected format when identifying the roles of "
                "the log's attributes. Please try again."
            )

        def _role(name: str, default):
            # The prompt asks for "<role>_attributes"; "<role>_columns" is accepted as well.
            value = parsed.get(f"{name}_attributes", parsed.get(f"{name}_columns", default))
            return value if value is not None else default

        if not isinstance(_role("switch", []), list) or not isinstance(_role("group", []), list):
            raise LLMError(
                "The language model returned an unexpected format when identifying the roles of "
                "the log's attributes. Please try again."
            )
        switch_cols = [c for c in _role("switch", []) if c in candidates]
        group_cols = [c for c in _role("group", []) if c in candidates]
        for c in switch_cols:
            if c not in group_cols:
                group_cols.append(c)

        raw_env = _role("environment", {})
        if not isinstance(raw_env, dict):
            raw_env = {}
        environment_columns: Dict[str, List[str]] = {}
        assigned = set()
        for env in _ENVIRONMENTS:  # richest first, so a column listed twice keeps its richer role
            cols = raw_env.get(env) or []
            if not isinstance(cols, list):
                cols = []
            environment_columns[env] = []
            for c in cols:
                if c in candidates and c not in assigned:
                    environment_columns[env].append(c)
                    assigned.add(c)
        raw_elements = _role("element", [])
        element_cols = [c for c in raw_elements if c in candidates] if isinstance(raw_elements, list) else []
        return {
            "group_columns": group_cols,
            "switch_columns": switch_cols,
            "environment_columns": environment_columns,
            "element_columns": element_cols,
        }

    def _extract_detected_field(self, response: str, fieldnames: List[str]) -> str:
        detected = (response or "").strip().strip('"').strip("'").strip("`")
        if not detected:
            return ""

        for field in fieldnames or []:
            if detected.lower() == (field or "").lower():
                return field

        lowered = detected.lower()
        for field in fieldnames or []:
            field_text = (field or "").lower()
            if field_text and field_text in lowered:
                return field

        return detected


def load_csv(filepath: str) -> List[Event]:
    """
    Convenience function to load CSV file.

    Args:
        filepath: Path to CSV file

    Returns:
        List of Event objects
    """
    loader = CSVLoader()
    return loader.load(filepath)
