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
