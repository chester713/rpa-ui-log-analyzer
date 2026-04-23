"""Event-to-activity mapping module."""

from typing import List, Dict, Any
from ..models.event import Event
from ..models.activity import Activity, EventActivityMapping
from ..inference.event_grouper import EventGrouper, EventGroup
from ..inference.activity_inferrer import ActivityInferrer


class EventActivityMapper:
    """Maps event groups to inferred activities."""

    def __init__(self, grouper: EventGrouper, inferrer: ActivityInferrer):
        """
        Initialize EventActivityMapper.

        Args:
            grouper: EventGrouper instance for grouping events
            inferrer: ActivityInferrer instance for inferring activities
        """
        self.grouper = grouper
        self.inferrer = inferrer

    def map(self, events: List[Event]) -> List[EventActivityMapping]:
        """
        Map events to activities through grouping and inference.

        Args:
            events: List of Event objects

        Returns:
            List of EventActivityMapping objects (main activities only, one per group).
            The full enriched list (including implicit prerequisite and context-switch
            activities) is stored on self.enriched_activities after this call.
        """
        if not events:
            self.enriched_activities = []
            return []

        groups = self.grouper.group_events_with_context_switches(events)

        # Pass EventGroup objects so the inferrer can read context-switch metadata
        all_activities = self.inferrer.infer_activities(groups)
        self.enriched_activities = all_activities

        # One main activity per group — preserves 1:1 mapping for downstream pipeline
        main_activities = [a for a in all_activities if a.activity_type == "main"]

        mappings = []
        for group, activity in zip(groups, main_activities):
            attribute_breakdown = self._build_attribute_breakdown(group.events)

            mapping = EventActivityMapping(
                activity=activity,
                events=group.events,
                confidence=activity.confidence,
                attribute_breakdown=attribute_breakdown,
            )

            if hasattr(group, "is_context_switch") and group.is_context_switch:
                mapping.attribute_breakdown["context_switch"] = True
                mapping.attribute_breakdown["previous_app"] = getattr(group, "previous_app", None)
                mapping.attribute_breakdown["current_app"] = getattr(group, "current_app", None)

            mappings.append(mapping)

        return mappings

    def _build_attribute_breakdown(self, event_group: List[Event]) -> Dict[str, Any]:
        """
        Build attribute breakdown showing which attributes were used.

        Args:
            event_group: List of Events in a group

        Returns:
            Dictionary with attribute statistics
        """
        attribute_counts = {}
        attribute_values = {}

        for event in event_group:
            for key, value in event.attributes.items():
                if value:
                    if key not in attribute_counts:
                        attribute_counts[key] = 0
                        attribute_values[key] = []
                    attribute_counts[key] += 1
                    if value not in attribute_values[key]:
                        attribute_values[key].append(value)

        return {
            "attribute_counts": attribute_counts,
            "shared_attributes": [
                key
                for key, count in attribute_counts.items()
                if count == len(event_group)
            ],
            "unique_attributes": attribute_values,
        }

    def get_mapping_summary(
        self, mappings: List[EventActivityMapping]
    ) -> Dict[str, Any]:
        """
        Get summary of all mappings.

        Args:
            mappings: List of EventActivityMapping objects

        Returns:
            Dictionary with mapping statistics
        """
        if not mappings:
            return {"total_mappings": 0, "total_events": 0, "avg_confidence": 0.0}

        return {
            "total_mappings": len(mappings),
            "total_events": sum(len(m.events) for m in mappings),
            "avg_confidence": sum(m.confidence for m in mappings) / len(mappings),
            "high_confidence_count": sum(1 for m in mappings if m.confidence >= 0.8),
            "low_confidence_count": sum(1 for m in mappings if m.confidence < 0.5),
        }
