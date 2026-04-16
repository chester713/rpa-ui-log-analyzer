"""CSV loader for UI log files."""

import csv
from typing import List, Dict, Any, Optional
from ..models.event import Event


class CSVLoader:
    """Loads CSV files and auto-detects event column."""

    EVENT_COLUMN_CANDIDATES = [
        "event",
        "activity",
        "action",
        "events",
        "description",
        "name",
        "text",
    ]

    def _detect_event_column(self, fieldnames: List[str]) -> Optional[str]:
        """Detect which column contains event data."""
        for candidate in self.EVENT_COLUMN_CANDIDATES:
            for field in fieldnames:
                if field.lower() == candidate.lower():
                    return field
        return None

    def load(self, filepath: str) -> List[Event]:
        """
        Load CSV file and return list of Event objects.

        Args:
            filepath: Path to CSV file

        Returns:
            List of Event objects

        Raises:
            ValueError: If no event column can be detected
            FileNotFoundError: If file doesn't exist
        """
        events = []

        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)

            event_column = self._detect_event_column(reader.fieldnames)

            if event_column is None:
                raise ValueError(
                    f"Could not detect event column. Found columns: {reader.fieldnames}. "
                    f"Expected one of: {', '.join(self.EVENT_COLUMN_CANDIDATES)}"
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
