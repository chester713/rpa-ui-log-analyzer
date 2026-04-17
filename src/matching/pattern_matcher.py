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
            context: Execution context (web, desktop, visual)

        Returns:
            Matching Pattern or None
        """
        action, obj = self._parse_activity_name(activity.name)
        action, obj = self._normalize_activity(action, obj, events)

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

        # Object normalization
        if any(k in obj_l for k in ["option", "dropdown", "combo", "list item"]):
            normalized_obj = "Option"
        elif any(
            k in obj_l for k in ["context", "window", "application", "app switch"]
        ):
            normalized_obj = "Context"
        else:
            # Most patterns in this library use Element
            normalized_obj = "Element"

        return normalized_action, normalized_obj


def get_context_from_events(events: List[Event]) -> str:
    """
    Extract execution context from event attributes.

    Args:
        events: List of Event objects

    Returns:
        Context string: "web", "desktop", or "visual"
    """
    context_scores = {"web": 0, "desktop": 0, "visual": 0}

    for event in events:
        attrs = event.attributes

        if "webpage" in attrs or "url" in attrs:
            context_scores["web"] += 2

        if "app" in attrs or "application" in attrs:
            context_scores["desktop"] += 2

        if "element_type" in attrs:
            elem_type = attrs["element_type"].lower()
            if "image" in elem_type or "icon" in elem_type:
                context_scores["visual"] += 1
            if "cell" in elem_type or "worksheet" in elem_type:
                context_scores["desktop"] += 1

        if "environment" in attrs:
            env = attrs["environment"].lower()
            if "web" in env:
                context_scores["web"] += 3
            elif "desktop" in env or "application" in env:
                context_scores["desktop"] += 3
            elif "visual" in env or "screen" in env:
                context_scores["visual"] += 3

    max_score = max(context_scores.values())
    if max_score == 0:
        return "web"

    for ctx, score in context_scores.items():
        if score == max_score:
            return ctx

    return "web"
