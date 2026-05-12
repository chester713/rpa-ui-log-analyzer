"""CSV loader for UI log files."""

import csv
import json
import logging
import re
from typing import List, Dict, Any, Optional
from ..models.event import Event

_logger = logging.getLogger(__name__)


class CSVLoader:
    """Loads CSV files and uses LLM to detect event column."""

    def __init__(self, llm_client=None):
        self.llm_client = llm_client
        self._force_column = None
        self.detected_column = None
        self.llm_recommended = False
        self.detected_group_columns: Optional[List[str]] = None
        self.detected_switch_columns: Optional[List[str]] = None

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

        prompt = f"""You are selecting the event/action column from a UI log CSV.

Columns:
{columns_str}

Sample values per column:
{"\n".join(sample_by_column)}

Choose the column whose values generally look like UI actions, usually verb+noun style labels.
Examples: activateWorkbook, openWindow, clickTextField, setValue, findElement.

Avoid columns that are timestamps, ids, URLs, application names, free-text descriptions, or long sentences.

Return only one exact column name from the list above. No explanation."""

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
    ) -> Dict[str, List[str]]:
        candidates = [f for f in (fieldnames or []) if f != exclude]
        if not candidates:
            return {"group_columns": [], "switch_columns": []}

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
        prompt = f"""You are analysing columns from a UI activity log CSV.

Columns (the event/action column has already been identified and is excluded):
{", ".join(candidates)}

Sample values per column:
{sample_str}

Identify two column sets:
1. "switch_columns": columns whose value identifies which application or process is active (e.g. app name, process, window title). A change in this value means the user switched to a different application.
2. "group_columns": columns useful for grouping consecutive events into the same activity (includes switch_columns plus things like URL, screen name, webpage, tab, element scope).

Rules:
- Only include column names that appear exactly in the list above.
- "switch_columns" must be a subset of "group_columns".
- Return empty lists if no column qualifies.
- Return only valid JSON, no explanation.

Format:
{{"switch_columns": ["col1"], "group_columns": ["col1", "col2"]}}"""

        response = self.llm_client.complete(prompt)
        clean = (response or "").strip()
        if clean.startswith("```"):
            clean = re.sub(r"```[a-z]*\n?", "", clean).strip("`").strip()
        parsed = json.loads(clean)
        switch_cols = [c for c in parsed.get("switch_columns", []) if c in candidates]
        group_cols = [c for c in parsed.get("group_columns", []) if c in candidates]
        for c in switch_cols:
            if c not in group_cols:
                group_cols.append(c)
        return {"group_columns": group_cols, "switch_columns": switch_cols}

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
