"""Pattern matcher for matching activities to patterns."""

from typing import List, Optional, Tuple
from ..models.event import Event
from ..models.activity import Activity
from ..models.pattern import Pattern, MethodRecommendation


class PatternMatcher:
    """Matches activities to RPA patterns."""

    def __init__(self, patterns: List[Pattern]):
        """
        Initialize PatternMatcher.

        Args:
            patterns: List of Pattern objects to match against
        """
        self.patterns = patterns

    def match(
        self, activity: Activity, events: List[Event], context: str
    ) -> Optional[Pattern]:
        """
        Find matching pattern for activity in given context.

        Args:
            activity: Inferred Activity
            events: Source events for the activity
            context: Execution context (web, desktop, screen, unknown)

        Returns:
            Matching Pattern or None
        """
        action, obj = self._parse_activity_name(activity.name)
        action, obj = self._normalize_activity(action, obj, events)

        for pattern in self.patterns:
            if pattern.matches_activity(action, obj, context):
                return pattern

        return None

    def create_implicit_recommendations(
        self, mappings, context_sequence: List[str]
    ) -> List[MethodRecommendation]:
        """Create implicit recommendations (Find + Switch Context)."""
        implicit = []
        seen_switches = set()
        seen_finds = set()

        # Add Switch Context recommendation on context transitions
        for i in range(1, len(mappings)):
            prev_ctx = context_sequence[i - 1]
            cur_ctx = context_sequence[i]
            if prev_ctx != cur_ctx:
                switch_key = (
                    prev_ctx,
                    cur_ctx,
                    tuple(mappings[i].activity.source_events or []),
                )
                if switch_key in seen_switches:
                    continue
                seen_switches.add(switch_key)

                switch_pattern = self._find_pattern_by_action_object(
                    "Switch", "Context", "desktop"
                )
                if switch_pattern:
                    implicit.append(
                        MethodRecommendation(
                            activity_name=f"Switch context from {prev_ctx} to {cur_ctx}",
                            activity_action="Switch",
                            activity_object="Context",
                            events=mappings[i].activity.source_events,
                            execution_environment="desktop",
                            pattern=switch_pattern,
                            method=switch_pattern.get_method_for_context("desktop"),
                            method_category=switch_pattern.category,
                            confidence=0.9,
                            confidence_explanation=(
                                "High confidence (0.90): explicit context transition detected "
                                f"from {prev_ctx} to {cur_ctx} between consecutive interaction groups."
                            ),
                            context_switch=True,
                            context_switch_from=prev_ctx,
                            context_switch_to=cur_ctx,
                        )
                    )

        # Add Find recommendation before Read/Write/Focus/Activate when identifiable
        for mapping, ctx in zip(mappings, context_sequence):
            action, obj = self._parse_activity_name(mapping.activity.name)
            action, obj = self._normalize_activity(action, obj, mapping.events)

            if action in {"Read", "Write", "Focus", "Activate"}:
                find_key = (action, ctx, tuple(mapping.activity.source_events or []))
                if find_key in seen_finds:
                    continue
                seen_finds.add(find_key)

                find_pattern = self._find_pattern_by_action_object(
                    "Find", "Element", ctx
                )
                if find_pattern:
                    implicit.append(
                        MethodRecommendation(
                            activity_name=f"Find target element for {action.lower()}",
                            activity_action="Find",
                            activity_object="Element",
                            events=mapping.activity.source_events,
                            execution_environment=ctx,
                            pattern=find_pattern,
                            method=find_pattern.get_method_for_context(ctx),
                            method_category=find_pattern.category,
                            confidence=0.85,
                            confidence_explanation=(
                                f"High confidence (0.85): '{action}' requires a target element to be identified first, "
                                "so Find is inferred as a prerequisite step."
                            ),
                        )
                    )

        return implicit

    def _find_pattern_by_action_object(
        self, action: str, obj: str, context: str
    ) -> Optional[Pattern]:
        for pattern in self.patterns:
            if pattern.matches_activity(action, obj, context):
                return pattern
        return None

    def match_all(
        self,
        activities: List[Activity],
        event_groups: List[List[Event]],
        contexts: List[str],
    ) -> List[MethodRecommendation]:
        """
        Match all activities to patterns and create recommendations.

        Args:
            activities: List of inferred Activities
            event_groups: List of event groups (one per activity)
            contexts: List of execution contexts (one per activity)

        Returns:
            List of MethodRecommendation objects
        """
        recommendations = []

        for activity, events, context in zip(activities, event_groups, contexts):
            pattern = self.match(activity, events, context)
            event_indices = [e.row_index for e in events if e.row_index is not None]

            method = pattern.get_method_for_context(context) if pattern else None

            recommendation = MethodRecommendation(
                activity_name=activity.name,
                activity_action=activity.evidence[0] if activity.evidence else "",
                activity_object=activity.evidence[1]
                if len(activity.evidence) > 1
                else "",
                events=event_indices,
                execution_environment=context,
                pattern=pattern,
                method=method,
                method_category=pattern.category if pattern else None,
                confidence=activity.confidence,
            )
            recommendations.append(recommendation)

        return recommendations

    def _parse_activity_name(self, activity_name: str) -> Tuple[str, str]:
        """
        Parse activity name into action and object.

        Args:
            activity_name: Activity name (e.g., "Activate element", "Write element")

        Returns:
            Tuple of (action, object)
        """
        parts = activity_name.split()
        if len(parts) >= 2:
            action = parts[0]
            obj = " ".join(parts[1:])
        else:
            action = activity_name
            obj = ""

        return action, obj

    def _normalize_activity(
        self, action: str, obj: str, events: List[Event]
    ) -> Tuple[str, str]:
        """Normalize inferred activity to pattern vocabulary (AOMC-aligned)."""
        event_text = " ".join([e.event.lower() for e in events])
        action_l = (action or "").strip().lower()
        obj_l = (obj or "").strip().lower()

        # Action normalization
        action_map = {
            "click": "Activate",
            "press": "Activate",
            "tap": "Activate",
            "activate": "Activate",
            "open": "Open",
            "launch": "Open",
            "new": "Open",
            "type": "Write",
            "input": "Write",
            "paste": "Write",
            "enter": "Write",
            "fill": "Write",
            "write": "Write",
            "set": "Write",
            "read": "Read",
            "extract": "Read",
            "get": "Read",
            "find": "Find",
            "locate": "Find",
            "observe": "Observe",
            "watch": "Observe",
            "scroll": "Scroll",
            "focus": "Focus",
            "refresh": "Refresh",
            "select": "Select",
            "hover": "Hover",
            "switch": "Switch",
            "delete": "Delete",
            "remove": "Delete",
            "disable": "Disable",
        }

        normalized_action = action_map.get(action_l)

        # Special case: click on text field/input is Focus, not Activate.
        first_attrs = events[0].attributes if events else {}
        is_text_input_target = any(
            k in (obj_l or "") for k in ["textfield", "text field", "input", "field"]
        ) or any(
            str(first_attrs.get(k, "")).lower()
            in ["input", "text", "textbox", "textfield"]
            for k in ["tag_name", "tag_type", "element_type"]
        )

        if normalized_action == "Activate" and (
            "clicktextfield" in event_text
            or "changefield" in event_text
            or is_text_input_target
        ):
            normalized_action = "Focus"

        # Heuristic fallback from event names when LLM uses free-form phrasing
        if not normalized_action:
            if any(k in event_text for k in ["click", "activate", "press"]):
                normalized_action = "Activate"
            elif any(k in event_text for k in ["open", "newworkbook", "openwindow"]):
                normalized_action = "Open"
            elif any(
                k in event_text for k in ["type", "paste", "changefield", "input"]
            ):
                normalized_action = "Write"
            elif any(k in event_text for k in ["getcell", "read", "extract"]):
                normalized_action = "Read"
            elif "select" in event_text:
                normalized_action = "Select"
            elif "scroll" in event_text:
                normalized_action = "Scroll"
            elif "focus" in event_text:
                normalized_action = "Focus"
            elif "refresh" in event_text:
                normalized_action = "Refresh"
            else:
                normalized_action = action.title() if action else "Activate"

        # Object normalization — use prefix/word-boundary match so that activity
        # names like "Write Microsoft Excel window in Excel" don't accidentally
        # match the "window" keyword and get mis-classified as Context.
        _ctx_keys = ["context", "window", "application", "app switch"]
        if any(k in obj_l for k in ["option", "dropdown", "combo", "list item"]):
            normalized_obj = "Option"
        elif any(obj_l == k or obj_l.startswith(k + " ") for k in _ctx_keys):
            normalized_obj = "Context"
        else:
            # Most patterns in this library use Element
            normalized_obj = "Element"

        return normalized_action, normalized_obj


def get_context_from_events(events: List[Event]) -> str:
    """
    Extract execution context from event attributes using priority-based rules.

    Priority order:
      1. Web   — HTML-property attributes present (XPath, tag, HTML id, browser URL)
      2. Desktop — application/UI-hierarchy attributes present, no HTML properties
      3. Screen  — coordinate attributes present, no HTML or app/hierarchy attributes
      4. Unknown — no distinguishing attributes found

    Returns:
        Context string: "web", "desktop", "screen", or "unknown"
    """
    _HTML_ATTRS = {
        "xpath", "xpath_full", "html_id", "tag_name", "tag_type",
        "tag_html", "tag_href", "browser_url", "webpage", "url",
    }
    _APP_ATTRS = {
        "application", "app", "window_title", "workbook", "worksheet",
        "cell_range", "cell_range_number", "control_type", "ui_path",
    }
    _COORD_ATTRS = {
        "x", "y", "mouse_x", "mouse_y", "coordinates", "coordinate",
        "click_x", "click_y",
    }

    has_html = False
    has_app = False
    has_coord = False

    for event in events:
        attrs = event.attributes
        if any(k in attrs and attrs[k] not in (None, "", "None", "none") for k in _HTML_ATTRS):
            has_html = True
            break  # highest priority — no need to check further

    if not has_html:
        for event in events:
            attrs = event.attributes
            if any(k in attrs and attrs[k] not in (None, "", "None", "none") for k in _APP_ATTRS):
                has_app = True
                break

    if not has_html and not has_app:
        for event in events:
            attrs = event.attributes
            if any(k in attrs and attrs[k] not in (None, "", "None", "none") for k in _COORD_ATTRS):
                has_coord = True
                break

    if has_html:
        return "web"
    if has_app:
        return "desktop"
    if has_coord:
        return "screen"
    return "unknown"
