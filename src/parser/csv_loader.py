"""CSV loader for UI log files."""

import csv
from typing import List, Dict, Any
from ..models.event import Event


class CSVLoader:
    """Loads CSV files and validates required columns."""

    REQUIRED_COLUMN = "event"

    def load(self, filepath: str) -> List[Event]:
        """
        Load CSV file and return list of Event objects.

        Args:
            filepath: Path to CSV file

        Returns:
            List of Event objects

        Raises:
            ValueError: If required 'event' column is missing
            FileNotFoundError: If file doesn't exist
        """
        events = []

        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)

            if self.REQUIRED_COLUMN not in reader.fieldnames:
                raise ValueError(f"Missing required column: {self.REQUIRED_COLUMN}")

            for row_index, row in enumerate(reader):
                event_name = row.get(self.REQUIRED_COLUMN, "").strip()

                attributes = {}
                for key, value in row.items():
                    if key != self.REQUIRED_COLUMN and value:
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
