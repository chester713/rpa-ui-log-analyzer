"""CSV loader for UI log files."""

import csv
import re
from typing import List, Dict, Any, Optional
from ..models.event import Event


class CSVLoader:
    """Loads CSV files and uses LLM to detect event column."""

    def __init__(self, llm_client=None):
        """
        Initialize CSVLoader.

        Args:
            llm_client: Optional LLM client for event column detection
        """
        self.llm_client = llm_client
        self._force_column = None
        self.detected_column = None

    def load(self, filepath: str) -> List[Event]:
        """
        Load CSV file and return list of Event objects.

        Uses LLM to detect which column contains event data.
        Events should be in verb + noun format (e.g., "ClickButton", "OpenBrowser").

        Args:
            filepath: Path to CSV file

        Returns:
            List of Event objects

        Raises:
            ValueError: If event column cannot be detected
            FileNotFoundError: If file doesn't exist
        """
        events = []

        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            rows = list(reader)

            if self._force_column:
                event_column = self._force_column
            else:
                event_column = self._detect_event_column_with_llm(
                    fieldnames, sample_rows=rows[:50]
                )

            self.detected_column = event_column

            if event_column is None:
                raise ValueError(
                    f"Missing required column: event (could not detect event column. Found columns: {fieldnames})"
                )

            for row_index, row in enumerate(rows):
                event_name = row.get(event_column, "").strip()

                attributes = {}
                for key, value in row.items():
                    if key != event_column and value:
                        attributes[key] = value

                events.append(
                    Event(event=event_name, attributes=attributes, row_index=row_index)
                )

        return events

    def _detect_event_column_with_llm(
        self, fieldnames: List[str], sample_rows: Optional[List[Dict[str, Any]]] = None
    ) -> Optional[str]:
        """
        Use LLM to detect which column contains event data.

        Args:
            fieldnames: List of column names from CSV

        Returns:
            Name of event column, or None if detection fails
        """
        if self.llm_client is None:
            return self._detect_event_column_fallback(fieldnames, sample_rows=sample_rows)

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

        try:
            response = self.llm_client.complete(prompt)
            detected = self._extract_detected_field(response, fieldnames)

            # Reject empty/invalid responses (e.g., unnamed index column).
            invalid = {"", "index", "row", "row_id", "#"}
            if detected.lower() in invalid:
                return self._detect_event_column_fallback(fieldnames, sample_rows=sample_rows)

            for field in fieldnames or []:
                field_name = (field or "").strip()
                if not field_name:
                    continue
                if field_name.lower() == detected.lower():
                    if sample_rows and len(sample_rows) >= 3:
                        llm_score = self._score_column_as_event(field, sample_rows)
                        best_field = field
                        best_score = llm_score
                        for candidate in fieldnames or []:
                            score = self._score_column_as_event(candidate, sample_rows)
                            if score > best_score:
                                best_field = candidate
                                best_score = score

                        if best_field != field and best_score >= llm_score + 0.2:
                            return best_field
                    return field

        except Exception:
            pass

        return self._detect_event_column_fallback(fieldnames, sample_rows=sample_rows)

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

    def _looks_like_action_event(self, value: str) -> float:
        text = (value or "").strip()
        if not text:
            return 0.0

        lower = text.lower()
        if len(text) > 120:
            return 0.0
        if lower.startswith(("http://", "https://", "www.")):
            return 0.0
        if re.search(r"\d{4}-\d{2}-\d{2}|\d{1,2}:\d{2}", text):
            return 0.0

        separators = ["_", "-", " "]
        if any(sep in text for sep in separators):
            tokens = re.split(r"[_\-\s]+", text)
        else:
            tokens = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", text)

        tokens = [t for t in tokens if t]
        if not tokens:
            return 0.0

        action_verbs = {
            "activate",
            "click",
            "open",
            "close",
            "set",
            "get",
            "read",
            "write",
            "type",
            "typed",
            "paste",
            "copy",
            "select",
            "find",
            "focus",
            "hover",
            "scroll",
            "refresh",
            "switch",
            "input",
            "change",
            "extract",
            "observe",
            "disable",
            "delete",
            "new",
            "link",
            "reload",
            "submit",
            "press",
        }

        first = tokens[0].lower()
        if first not in action_verbs:
            return 0.0

        if len(tokens) >= 2:
            return 1.0
        return 0.6

    def _score_column_as_event(
        self, field: str, sample_rows: Optional[List[Dict[str, Any]]]
    ) -> float:
        rows = sample_rows or []
        if not rows:
            return 0.0

        non_empty = 0
        scores = []
        for row in rows:
            value = str((row or {}).get(field, "")).strip()
            if not value:
                continue
            non_empty += 1
            scores.append(self._looks_like_action_event(value))

        if non_empty == 0:
            return 0.0

        density = non_empty / len(rows)
        avg = sum(scores) / non_empty
        base_score = avg * density

        field_l = (field or "").strip().lower()
        if field_l in {
            "concept:name",
            "event",
            "event_type",
            "activity",
            "action",
            "events",
            "name",
        }:
            base_score += 0.08

        return round(base_score, 4)

    def _detect_event_column_fallback(
        self, fieldnames: List[str], sample_rows: Optional[List[Dict[str, Any]]] = None
    ) -> Optional[str]:
        """Fallback detection using sample values first, then common names."""
        sample_rows = sample_rows or []
        if sample_rows and fieldnames:
            best_field = None
            best_score = 0.0
            for field in fieldnames:
                score = self._score_column_as_event(field, sample_rows)
                if score > best_score:
                    best_score = score
                    best_field = field

            if best_field and best_score >= 0.45:
                return best_field

        normalized = [f for f in fieldnames if (f or "").strip()]
        candidates = [
            "event_type",
            "event",
            "activity",
            "action",
            "events",
            "name",
            "text",
        ]
        for candidate in candidates:
            for field in normalized:
                if field.lower() == candidate.lower():
                    return field
        return None


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
