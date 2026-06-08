"""Pattern matcher for matching activities to patterns."""

from typing import List, Optional
from ..models.event import Event
from ..models.activity import Activity
from ..models.pattern import Pattern


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
        llm_pattern_name = getattr(activity, "pattern_name", None)
        if llm_pattern_name:
            for pattern in self.patterns:
                if pattern.name.lower() == llm_pattern_name.strip().lower():
                    if not pattern.contexts or context in pattern.contexts:
                        return pattern

        return None


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
