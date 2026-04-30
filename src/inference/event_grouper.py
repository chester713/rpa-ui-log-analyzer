"""Event grouper for grouping consecutive events by shared attributes."""

from typing import List, Optional, Tuple
from dataclasses import dataclass
from ..models.event import Event


@dataclass
class EventGroup:
    """Represents a group of events with context information."""

    events: List[Event]
    is_context_switch: bool = False
    previous_app: Optional[str] = None
    current_app: Optional[str] = None


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

    CONTEXT_SWITCH_ATTRIBUTES = ["app", "application"]

    def __init__(
        self,
        group_attributes: Optional[List[str]] = None,
        context_switch_attributes: Optional[List[str]] = None,
    ):
        self.group_attributes = group_attributes or self.DEFAULT_GROUP_ATTRIBUTES
        self.context_switch_attributes = (
            context_switch_attributes or self.CONTEXT_SWITCH_ATTRIBUTES
        )

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
        groups = self._group_events_with_context(events)
        return [g.events for g in groups]

    def group_events_with_context_switches(
        self, events: List[Event]
    ) -> List[EventGroup]:
        """
        Group events and detect context switches.

        When consecutive events have different application attributes, this
        indicates a context switch (focus shifted from one application to another).
        This is important for bot design as it represents implicit user behavior.

        Args:
            events: List of Event objects in temporal order

        Returns:
            List of EventGroup objects with context switch detection
        """
        return self._group_events_with_context(events)

    def _group_events_with_context(self, events: List[Event]) -> List[EventGroup]:
        """Internal method to group events with context tracking."""
        if not events:
            return []

        groups = []
        current_group = EventGroup(events=[events[0]])

        for event in events[1:]:
            app_attr = self._get_application_attribute(event)
            prev_app = self._get_application_attribute(current_group.events[-1])

            is_context_switch = self._is_context_switch(current_group.events[-1], event)

            if is_context_switch:
                current_group.is_context_switch = True
                groups.append(current_group)
                current_group = EventGroup(
                    events=[event], previous_app=prev_app, current_app=app_attr
                )
            elif self._events_share_attribute(current_group.events[-1], event):
                current_group.events.append(event)
            else:
                groups.append(current_group)
                current_group = EventGroup(events=[event])

        if current_group.events:
            groups.append(current_group)

        return groups

    def _get_application_attribute(self, event: Event) -> Optional[str]:
        """Get application attribute from event."""
        for attr in self.context_switch_attributes:
            if attr in event.attributes:
                return event.attributes[attr]
        return None

    def _is_context_switch(self, event1: Event, event2: Event) -> bool:
        """
        Check if there's a context switch between two events.

        A context switch occurs when the application attribute changes,
        indicating focus shifted from one application to another.

        Args:
            event1: First event
            event2: Second event

        Returns:
            True if events have different application attributes
        """
        app1 = self._get_application_attribute(event1)
        app2 = self._get_application_attribute(event2)

        if app1 is None and app2 is None:
            return False
        if app1 is None or app2 is None:
            return True
        return app1 != app2

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
