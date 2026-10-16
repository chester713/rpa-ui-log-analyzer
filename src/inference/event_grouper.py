"""Event grouper for grouping consecutive events by shared attributes."""

import json
import logging
import re
from typing import Dict, List, Optional, Tuple
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
        Group events and propose application-switch boundaries.

        When a recorded application value differs from the last recorded one, the
        current group closes and a new one starts: a *candidate* switch for the
        LLM refinement pass and activity naming to confirm or reject. An event
        with no application value is never treated as a switch (a missing value
        is no evidence either way); the next recorded value is compared with the
        last recorded application instead.

        Args:
            events: List of Event objects in temporal order

        Returns:
            List of EventGroup objects with candidate switch boundaries
        """
        return self._group_events_with_context(events)

    def _group_events_with_context(self, events: List[Event]) -> List[EventGroup]:
        """Internal method to group events with context tracking."""
        if not events:
            return []

        groups = []
        current_group = EventGroup(events=[events[0]])
        last_app = self._get_application_attribute(events[0])

        for event in events[1:]:
            app = self._get_application_attribute(event)
            application_changed = (
                app is not None and last_app is not None and app != last_app
            )

            if application_changed:
                current_group.is_context_switch = True
                groups.append(current_group)
                current_group = EventGroup(
                    events=[event], previous_app=last_app, current_app=app
                )
            elif self._events_share_attribute(current_group.events[-1], event):
                current_group.events.append(event)
            else:
                groups.append(current_group)
                current_group = EventGroup(events=[event])

            if app is not None:
                last_app = app

        if current_group.events:
            groups.append(current_group)

        return groups

    def _get_application_attribute(self, event: Event) -> Optional[str]:
        """The application recorded for an event, or None when the log has none."""
        for attr in self.context_switch_attributes:
            value = event.recorded(attr)
            if value is not None:
                return value
        return None

    def _events_share_attribute(self, event1: Event, event2: Event) -> bool:
        """
        Check if two events share at least one grouping attribute.

        Args:
            event1: First event
            event2: Second event

        Returns:
            True if events share at least one recorded attribute value
        """
        for attr in self.group_attributes:
            val1 = event1.recorded(attr)
            val2 = event2.recorded(attr)

            if val1 is not None and val1 == val2:
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
    """Second pass: the LLM turns the candidate groups into UI activities.

    Rule-based pre-segmentation by context both over- and under-segments: one
    intention can be split across adjacent groups, and one group can hold several
    intentions (clicking a text field, which focuses it, then pasting into it).
    The LLM therefore receives the events of a batch of candidate groups, numbered
    consecutively, and returns runs of consecutive event numbers, one per UI
    activity. It may divide a group and combine events of directly adjacent groups.

    Between every pair of adjacent groups it is shown evidence from the log itself
    (the application-related attributes first, then URL, window and element values)
    and is told that a changed application counts strongly against combining while
    a missing value is no evidence either way. The code does not override its
    answer; it only validates that every run is consecutive and that every event is
    covered exactly once. There is no fallback: a missing LLM or an invalid response
    raises instead of returning the candidate groups unchanged.
    """

    BATCH_SIZE = 10
    _DEFAULT_APPLICATION_KEYS = ("application", "app", "process")
    _DEFAULT_CONTEXT_KEYS = ("url", "browser_url", "webpage", "window", "window_title")
    _MAX_CONTEXT_COLUMNS = 4
    _MAX_VALUE_CHARS = 60

    def __init__(
        self,
        llm_client=None,
        application_attributes: Optional[List[str]] = None,
        context_attributes: Optional[List[str]] = None,
        element_attributes: Optional[List[str]] = None,
    ):
        """
        Args:
            llm_client: LLM used to decide the UI activities.
            application_attributes: Columns that identify the active application, as
                identified by the LLM when the log was loaded. Defaults to common names.
            context_attributes: Other columns that locate an event (URL, window,
                element, ...). Defaults to common names.
            element_attributes: Columns that identify the target UI element; their
                values are shown next to each event so the LLM can tell targets apart.
        """
        self.llm_client = llm_client
        self.application_attributes = list(application_attributes or self._DEFAULT_APPLICATION_KEYS)
        self.context_attributes = [
            key
            for key in (context_attributes or self._DEFAULT_CONTEXT_KEYS)
            if key not in self.application_attributes
        ]
        self.element_attributes = list(element_attributes or [])

    def refine(self, groups: List[EventGroup]) -> List[EventGroup]:
        """Return the UI activities decided by the LLM, as event groups."""
        if not groups or sum(len(g.events) for g in groups) <= 1:
            return groups
        if self.llm_client is None:
            raise ValueError("LLM client required for group refinement")
        result = []
        for i in range(0, len(groups), self.BATCH_SIZE):
            result.extend(self._refine_batch(groups[i:i + self.BATCH_SIZE]))
        return result

    # ── private ──────────────────────────────────────────────────────────────

    def _refine_batch(self, batch: List[EventGroup]) -> List[EventGroup]:
        event_count = sum(len(g.events) for g in batch)
        if event_count <= 1:
            return batch
        prompt = self._build_prompt(batch)
        _logger.debug("=== LLMGroupRefiner prompt ===\n%s\n=== end prompt ===", prompt)
        response = self.llm_client.complete(prompt)
        _logger.debug("=== LLMGroupRefiner response ===\n%s\n=== end response ===", response)
        runs = self._parse_response(response, event_count)
        return self._apply_runs(batch, runs)

    def _build_prompt(self, batch: List[EventGroup]) -> str:
        sections = []
        last_recorded: Dict[str, Tuple[str, int]] = {}  # attribute -> (value, group index)
        first_number = 0
        for i, group in enumerate(batch):
            sections.append(self._group_section(i, group, first_number))
            first_number += len(group.events)
            if i + 1 < len(batch):
                sections.append(self._boundary_evidence(i, group, batch[i + 1], last_recorded))
            for key in list(self.application_attributes) + list(self._context_columns_in(group)):
                value = self._edge_value(group, key, last=True)
                if value is not None:
                    last_recorded[key] = (value, i)

        n = len(batch)
        m = first_number
        application_columns = ", ".join(self.application_attributes)
        return f"""You are grouping UI events into UI activities for RPA design.
Each UI activity is one action a bot performs on one target, such as focusing a text field, writing a value into a field, activating a button or reading a cell.

Below are {n} candidate event groups from rule-based pre-segmentation by context, in temporal order, holding {m} events numbered [0] to [{m - 1}].
Between every two adjacent groups you are given evidence taken from the log's own attributes.
Application-related attributes in this log: {application_columns}.

{chr(10).join(sections)}

How events form one UI activity:
- Events that repeat the same action on the same target belong together (e.g. several input or keystroke events that type one value into one field).
- Events that only record the effect of an action belong to that action (e.g. a field-change or value-changed event recorded after a value was typed or pasted into the field).
- A click that gives a text field focus before a value is typed or pasted into it is a UI activity of its own (focusing the field), not part of the writing.
- Actions on different targets are different UI activities.
You may therefore divide a candidate group into several UI activities, and you may combine events of directly adjacent groups.

Whether events on either side of a group boundary belong to the same UI activity is your decision; base it on that evidence:
- A recorded application that CHANGED between two groups means the user switched application.
  Do not combine across it unless the two values clearly name the same application
  (for example "Chrome" and "chrome.exe").
- An application that is NOT RECORDED on one side is not evidence of a switch. Decide from the
  other attributes and from the events themselves.
- A changed URL, window or element also counts against combining, but less strongly than a changed
  application.
- When the evidence does not show that events across a boundary serve one intention, keep them apart.

Rules:
1. Every UI activity is a run of CONSECUTIVE event numbers, such as [3,4,5]. Skipping an event,
   as in [3,5], is NEVER allowed: the events are in strict temporal order.
2. Every event number from 0 to {m - 1} must appear in exactly one UI activity.

Return a JSON array of arrays, one inner array of event numbers per UI activity, in order.

VALID   (6 events):                [[0],[1,2],[3],[4,5]]
INVALID (skips an event, forbidden): [[0],[1,3],[2],[4,5]]

Return only valid JSON. No explanation."""

    # ── evidence shown to the LLM ────────────────────────────────────────────

    def _clip(self, text: str) -> str:
        if len(text) <= self._MAX_VALUE_CHARS:
            return text
        return text[: self._MAX_VALUE_CHARS - 3] + "..."

    @staticmethod
    def _edge_value(group: EventGroup, key: str, last: bool) -> Optional[str]:
        """The first (or last) recorded value of an attribute within a group."""
        events = reversed(group.events) if last else group.events
        for event in events:
            value = event.recorded(key)
            if value is not None:
                return value
        return None

    @staticmethod
    def _distinct_values(group: EventGroup, key: str) -> List[str]:
        values: List[str] = []
        for event in group.events:
            value = event.recorded(key)
            if value is not None and value not in values:
                values.append(value)
        return values

    def _context_columns_in(self, *groups: EventGroup) -> List[str]:
        """Context columns recorded in at least one of the groups (capped)."""
        found = [
            key
            for key in self.context_attributes
            if any(self._distinct_values(group, key) for group in groups)
        ]
        return found[: self._MAX_CONTEXT_COLUMNS]

    def _group_section(self, index: int, group: EventGroup, first_number: int = 0) -> str:
        parts = []
        for key in self.application_attributes:
            values = self._distinct_values(group, key)
            if values:
                parts.append(f"{key}: " + " / ".join(self._clip(v) for v in values[:3]))
        if not parts:
            parts.append("application: not recorded")
        for key in self._context_columns_in(group):
            values = self._distinct_values(group, key)
            parts.append(f"{key}: " + " / ".join(self._clip(v) for v in values[:3]))

        lines = []
        for offset, event in enumerate(group.events):
            target = next(
                (event.recorded(k) for k in self.element_attributes if event.recorded(k) is not None),
                None,
            )
            suffix = f" (target: {self._clip(target)})" if target else ""
            lines.append(f"  [{first_number + offset}] {event.event}{suffix}")
        event_lines = "\n".join(lines) or "  - (none)"
        return f"GROUP {index} [{' | '.join(parts)}]\nEvents:\n{event_lines}"

    def _boundary_evidence(
        self,
        index: int,
        left: EventGroup,
        right: EventGroup,
        last_recorded: Dict[str, Tuple[str, int]],
    ) -> str:
        """One line comparing the end of ``left`` with the start of ``right``.

        ``last_recorded`` holds, per application and context attribute, the latest value
        recorded in the groups *before* ``left``; it is used when ``left`` recorded none,
        so a group without a value does not hide what the value was.
        """
        checks = [
            self._compare(key, left, right, index, last_recorded.get(key))
            for key in self.application_attributes
        ]
        if all(check is None for check in checks):
            checks = ["application NOT RECORDED in either group"]
        else:
            checks = [check for check in checks if check is not None]
        for key in self._context_columns_in(left, right):
            check = self._compare(key, left, right, index, last_recorded.get(key))
            if check is not None:
                checks.append(check)
        return f"  >> between GROUP {index} and GROUP {index + 1}: " + "; ".join(checks)

    def _compare(
        self,
        key: str,
        left: EventGroup,
        right: EventGroup,
        index: int,
        earlier: Optional[Tuple[str, int]] = None,
    ) -> Optional[str]:
        """Describe how ``key`` differs across a boundary, or None if neither side records it."""
        before = self._edge_value(left, key, last=True)
        after = self._edge_value(right, key, last=False)
        if before is None and after is None:
            return None
        if after is None:
            return f"{key} NOT RECORDED in GROUP {index + 1} (no evidence either way)"
        if before is not None:
            if before == after:
                return f"{key} same ({self._clip(before)})"
            return f"{key} CHANGED {self._clip(before)} -> {self._clip(after)}"
        # Nothing recorded in ``left``: fall back to the last value recorded before it.
        if earlier is None:
            return f"{key} NOT RECORDED in GROUP {index} (no earlier value to compare with)"
        value, source = earlier
        verdict = "same as" if value == after else "CHANGED from"
        return (
            f"{key} NOT RECORDED in GROUP {index}; last recorded {self._clip(value)} in GROUP {source}, "
            f"GROUP {index + 1} has {self._clip(after)} ({verdict} that)"
        )

    def _parse_response(self, response: str, n: int) -> List[List[int]]:
        """Parse and validate the runs of event numbers returned by the LLM.

        ``n`` is the number of events in the batch.
        """
        text = (response or "").strip()
        if text.startswith("```"):
            text = re.sub(r"```[a-z]*\n?", "", text).strip("`").strip()
        arr_match = re.search(r'\[.*\]', text, re.DOTALL)
        if not arr_match:
            raise ValueError("The LLM did not return a valid group structure. Please try again.")
        parsed = json.loads(arr_match.group())
        if not isinstance(parsed, list):
            raise ValueError("The LLM returned an unexpected response format for group refinement. Please try again.")

        seen = set()
        for run in parsed:
            if not isinstance(run, list) or not run:
                raise ValueError("The LLM returned an invalid group structure. Please try again.")
            for idx in run:
                if not isinstance(idx, int) or idx < 0 or idx >= n or idx in seen:
                    raise ValueError("The LLM returned an invalid group structure. Please try again.")
                seen.add(idx)
        if seen != set(range(n)):
            raise ValueError("The LLM returned an incomplete group structure. Please try again.")

        for run in parsed:
            ordered = sorted(run)
            if ordered != list(range(ordered[0], ordered[0] + len(ordered))):
                raise ValueError("The LLM attempted to group non-consecutive events, which is not allowed. Please try again.")

        return sorted((sorted(run) for run in parsed), key=lambda r: r[0])

    def _apply_runs(self, batch: List[EventGroup], runs: List[List[int]]) -> List[EventGroup]:
        """Build one event group per run of consecutive event numbers."""
        flat: List[Tuple[Event, int, bool]] = []  # (event, source group, first event of that group)
        for g_idx, group in enumerate(batch):
            for offset, event in enumerate(group.events):
                flat.append((event, g_idx, offset == 0))

        result = []
        for run in runs:
            events = [flat[i][0] for i in run]
            _, source, starts_group = flat[run[0]]
            if starts_group:
                origin = batch[source]
                result.append(EventGroup(
                    events=events,
                    is_context_switch=origin.is_context_switch,
                    previous_app=origin.previous_app,
                    current_app=origin.current_app,
                ))
            else:
                result.append(EventGroup(events=events))
        return result
