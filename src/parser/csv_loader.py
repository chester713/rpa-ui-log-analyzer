"""CSV loader for UI log files."""

import csv
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

            if self._force_column:
                event_column = self._force_column
            else:
                event_column = self._detect_event_column_with_llm(fieldnames)

            if event_column is None:
                raise ValueError(
                    f"Could not detect event column. Found columns: {fieldnames}"
                )

            for row_index, row in enumerate(reader):
                event_name = row.get(event_column, "").strip()

                attributes = {}
                for key, value in row.items():
                    if key != event_column and value:
                        attributes[key] = value

                events.append(
                    Event(event=event_name, attributes=attributes, row_index=row_index)
                )

        return events

    def _detect_event_column_with_llm(self, fieldnames: List[str]) -> Optional[str]:
        """
        Use LLM to detect which column contains event data.

        Args:
            fieldnames: List of column names from CSV

        Returns:
            Name of event column, or None if detection fails
        """
        if self.llm_client is None:
            return self._detect_event_column_fallback(fieldnames)

        columns_str = ", ".join(fieldnames)
        prompt = f"""Given these column names from a UI interaction log CSV file:
{columns_str}

Which column contains the event/activity data? Events are actions in verb+noun format like "ClickButton", "OpenBrowser", "FillForm", "SelectOption".

Respond with only the column name, nothing else."""

        try:
            response = self.llm_client.complete(prompt)
            detected = response.strip()

            for field in fieldnames:
                if field.lower() == detected.lower():
                    return field

        except Exception:
            pass

        return self._detect_event_column_fallback(fieldnames)

    def _detect_event_column_fallback(self, fieldnames: List[str]) -> Optional[str]:
        """Fallback detection using common column names."""
        candidates = [
            "event",
            "activity",
            "action",
            "events",
            "description",
            "name",
            "text",
        ]
        for candidate in candidates:
            for field in fieldnames:
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
