"""Event data model for UI log events."""

from typing import Dict, Any, Optional

# Spellings that mean "the logger recorded nothing here".
_NOT_RECORDED = {"", "none", "null", "nan"}


def recorded_value(value: Any) -> Optional[str]:
    """Return an attribute value as stripped text, or None when it was not recorded.

    A missing application (or URL, window, ...) is the absence of information, not
    a value: it must never be compared as if it were a different application.
    """
    if value is None:
        return None
    text = str(value).strip()
    return None if text.lower() in _NOT_RECORDED else text


class Event:
    """Represents a single event in a UI log."""

    def __init__(
        self,
        event: str,
        attributes: Optional[Dict[str, Any]] = None,
        row_index: Optional[int] = None,
    ):
        """
        Initialize an Event.

        Args:
            event: The event/activity description
            attributes: Dictionary of event attributes (context info)
            row_index: Row number in the original CSV
        """
        self.event = event
        self.attributes = attributes or {}
        self.row_index = row_index

    def __repr__(self) -> str:
        return f"Event(event='{self.event}', row_index={self.row_index})"

    def __eq__(self, other) -> bool:
        if not isinstance(other, Event):
            return False
        return (
            self.event == other.event
            and self.attributes == other.attributes
            and self.row_index == other.row_index
        )

    def has_attribute(self, key: str) -> bool:
        """Check if event has a specific attribute."""
        return key in self.attributes and self.attributes[key]

    def get_attribute(self, key: str, default: Any = None) -> Any:
        """Get attribute value with optional default."""
        return self.attributes.get(key, default)

    def recorded(self, key: str) -> Optional[str]:
        """The recorded value of an attribute, or None when the log has none."""
        return recorded_value(self.attributes.get(key))
