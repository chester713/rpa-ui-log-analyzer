"""Event grouper for grouping consecutive events by shared attributes."""

import json
import logging
import re
from typing import List, Optional, Tuple
from dataclasses import dataclass
from ..models.event import Event

_logger = logging.getLogger(__name__)


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


class LLMGroupRefiner:
    """Second-pass refinement: asks LLM to merge over-segmented candidate groups
    that share the same user intent into single activity groups.

    App-switch boundaries from Pass 1 are always preserved as hard constraints.
    Falls back to the candidate groups unchanged if the LLM is unavailable or fails.
    """

    BATCH_SIZE = 10
    _CONTEXT_APP_KEYS = ("application", "app", "process")
    _CONTEXT_EXTRA_KEYS = ("url", "browser_url", "webpage", "window")

    def __init__(self, llm_client=None):
        self.llm_client = llm_client

    def refine(self, groups: List[EventGroup]) -> List[EventGroup]:
        """Return LLM-merged groups."""
        if len(groups) <= 1:
            return groups
        if self.llm_client is None:
            raise ValueError("LLM client required for group refinement")
        result = []
        for i in range(0, len(groups), self.BATCH_SIZE):
            result.extend(self._refine_batch(groups[i:i + self.BATCH_SIZE]))
        return result

    # ── private ──────────────────────────────────────────────────────────────

    def _refine_batch(self, batch: List[EventGroup]) -> List[EventGroup]:
        if len(batch) == 1:
            return batch
        response = self.llm_client.complete(self._build_prompt(batch))
        merge_sets = self._parse_response(response, len(batch))
        return self._apply_merges(batch, merge_sets)

    def _build_prompt(self, batch: List[EventGroup]) -> str:
        sections = []
        for i, group in enumerate(batch):
            header = f"GROUP {i}"
            if group.is_context_switch:
                header += " [APP SWITCH]"

            first = group.events[0] if group.events else None
            ctx_parts = []
            if first:
                for key in self._CONTEXT_APP_KEYS:
                    val = (first.attributes.get(key) or "").strip()
                    if val:
                        ctx_parts.append(f"{key}: {val}")
                        break
                for key in self._CONTEXT_EXTRA_KEYS:
                    val = (first.attributes.get(key) or "").strip()
                    if val:
                        ctx_parts.append(f"{key}: {val}")
                        break

            ctx_str = ", ".join(ctx_parts) if ctx_parts else "no context"
            event_lines = "\n".join(f"  - {e.event}" for e in group.events) or "  - (none)"
            sections.append(f"{header} [{ctx_str}]\nEvents:\n{event_lines}")

        n = len(batch)
        return f"""You are grouping UI events into discrete tasks for RPA design.
Each task must correspond to exactly one user intention — one atomic action a bot would automate.

Below are {n} candidate event groups from rule-based pre-segmentation, in temporal order.
Groups marked [APP SWITCH] are hard boundaries — never merge across them.

{chr(10).join(sections)}

Decide which adjacent groups belong to the same single activity and should be merged.
Return a JSON array of arrays. Each inner array lists the group indices (0-based) to merge.
Every index from 0 to {n - 1} must appear exactly once. Indices within each set must be consecutive.
Never merge across [APP SWITCH] boundaries.

Return only valid JSON. No explanation.
[example for 5 groups where 1+2 merge: [[0],[1,2],[3],[4]]]"""

    def _parse_response(self, response: str, n: int) -> List[List[int]]:
        """Parse and validate merge sets from LLM response."""
        text = (response or "").strip()
        if text.startswith("```"):
            text = re.sub(r"```[a-z]*\n?", "", text).strip("`").strip()
        arr_match = re.search(r'\[.*\]', text, re.DOTALL)
        if not arr_match:
            raise ValueError(f"LLM group refinement response contains no JSON array: {text[:200]}")
        parsed = json.loads(arr_match.group())
        if not isinstance(parsed, list):
            raise ValueError("LLM group refinement response is not a list")

        seen = set()
        for s in parsed:
            if not isinstance(s, list) or not s:
                raise ValueError(f"Invalid merge set in LLM response: {s}")
            for idx in s:
                if not isinstance(idx, int) or idx < 0 or idx >= n or idx in seen:
                    raise ValueError(f"Invalid index {idx} in LLM group refinement response")
                seen.add(idx)
        if seen != set(range(n)):
            raise ValueError("LLM group refinement response missing some group indices")

        for s in parsed:
            sorted_s = sorted(s)
            if sorted_s != list(range(sorted_s[0], sorted_s[0] + len(sorted_s))):
                raise ValueError(f"Non-consecutive indices in merge set: {s}")

        return parsed

    def _apply_merges(self, batch: List[EventGroup], merge_sets: List[List[int]]) -> List[EventGroup]:
        """Apply LLM-specified merge sets."""
        result = []
        for merge_set in sorted(merge_sets, key=lambda s: s[0]):
            if len(merge_set) == 1:
                result.append(batch[merge_set[0]])
            else:
                merged_events: List[Event] = []
                for idx in merge_set:
                    merged_events.extend(batch[idx].events)
                first = batch[merge_set[0]]
                result.append(EventGroup(
                    events=merged_events,
                    is_context_switch=first.is_context_switch,
                    previous_app=first.previous_app,
                    current_app=first.current_app,
                ))
        return result
