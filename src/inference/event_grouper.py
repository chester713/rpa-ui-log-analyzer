"""Event grouper for grouping consecutive events by shared attributes."""

from typing import List, Optional
from ..models.event import Event


class EventGrouper:
    """Groups consecutive events that share common attributes."""

    DEFAULT_GROUP_ATTRIBUTES = [
        "app",
        "webpage",
        "element_id",
        "url",
        "application",
        "window",
    ]

    def __init__(self, group_attributes: Optional[List[str]] = None):
        """
        Initialize EventGrouper.

        Args:
            group_attributes: List of attribute names to use for grouping.
                             Defaults to common UI interaction attributes.
        """
        self.group_attributes = group_attributes or self.DEFAULT_GROUP_ATTRIBUTES

    def group_events(self, events: List[Event]) -> List[List[Event]]:
        """
        Group consecutive events that share at least one grouping attribute.

        Events are grouped if they are consecutive AND share at least one
        attribute value from group_attributes.

        Args:
            events: List of Event objects in temporal order

        Returns:
            List of event groups (each group is a list of Events)
        """
        if not events:
            return []

        groups = []
        current_group = [events[0]]

        for event in events[1:]:
            if self._events_share_attribute(current_group[-1], event):
                current_group.append(event)
            else:
                groups.append(current_group)
                current_group = [event]

        if current_group:
            groups.append(current_group)

        return groups

    def _events_share_attribute(self, event1: Event, event2: Event) -> bool:
        """
        Check if two events share at least one grouping attribute.

        Args:
            event1: First event
            event2: Second event

        Returns:
            True if events share at least one non-empty attribute value
        """
        for attr in self.group_attributes:
            val1 = event1.attributes.get(attr)
            val2 = event2.attributes.get(attr)

            if val1 and val2 and val1 == val2:
                return True

        return False

    def get_group_summary(self, groups: List[List[Event]]) -> dict:
        """
        Get summary statistics for event groups.

        Args:
            groups: List of event groups

        Returns:
            Dictionary with group statistics
        """
        return {
            "total_events": sum(len(g) for g in groups),
            "total_groups": len(groups),
            "avg_group_size": sum(len(g) for g in groups) / len(groups)
            if groups
            else 0,
            "group_sizes": [len(g) for g in groups],
        }
