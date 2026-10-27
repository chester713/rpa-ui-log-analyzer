"""Pattern matcher for matching activities to patterns."""

from typing import Dict, List, Optional, Tuple
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

    def match(self, activity: Activity) -> Optional[Pattern]:
        """
        Resolve the pattern the LLM assigned to ``activity``.

        Matching is by name only (case-insensitive). Whether the pattern has a
        variant for the activity's execution environment is decided later, when
        the method is chosen (see ``Pattern.get_method_for_context`` and
        ``explain_missing_method``), so an activity keeps its pattern even when
        that pattern cannot be carried out in the detected environment.

        Args:
            activity: Inferred Activity

        Returns:
            Matching Pattern or None when the name is missing or unknown
        """
        llm_pattern_name = getattr(activity, "pattern_name", None)
        if llm_pattern_name:
            for pattern in self.patterns:
                if pattern.name.lower() == llm_pattern_name.strip().lower():
                    return pattern

        return None


# Attribute names a hand-written log usually uses for each environment. Used only when
# a caller supplies no environment columns (older stored analyses, direct callers);
# the pipelines always pass the columns the LLM identified when the log was loaded,
# because column names differ between loggers.
DEFAULT_ENVIRONMENT_COLUMNS: Dict[str, List[str]] = {
    "web": [
        "xpath", "xpath_full", "html_id", "tag_name", "tag_type",
        "tag_html", "tag_href", "browser_url", "webpage", "url",
    ],
    "desktop": [
        "application", "app", "window_title", "workbook", "worksheet",
        "cell_range", "cell_range_number", "control_type", "ui_path",
    ],
    "screen": [
        "x", "y", "mouse_x", "mouse_y", "coordinates", "coordinate",
        "click_x", "click_y",
    ],
}

# Richest interface information first: the priority order of the environments.
ENVIRONMENT_PRIORITY = ("web", "desktop", "screen")


def environment_evidence(
    events: List[Event],
    environment_columns: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, Dict[str, object]]:
    """What the events of a UI activity record for each environment's indicator columns.

    Returns, for every environment in priority order, the indicator columns that were
    checked (``"checked"``) and those among them the events record, each with its first
    recorded value (``"recorded"``). ``determine_environment`` decides from this.
    """
    columns = DEFAULT_ENVIRONMENT_COLUMNS if environment_columns is None else environment_columns
    evidence: Dict[str, Dict[str, object]] = {}
    for environment in ENVIRONMENT_PRIORITY:
        checked = list(columns.get(environment) or [])
        recorded: Dict[str, str] = {}
        for column in checked:
            for event in events:
                value = event.recorded(column)
                if value is not None:
                    recorded[column] = value
                    break
        evidence[environment] = {"checked": checked, "recorded": recorded}
    return evidence


def richest_environment(evidence: Dict[str, Dict[str, object]]) -> Tuple[str, Dict[str, str]]:
    """The highest-priority environment with a recorded indicator, and those indicators."""
    for environment in ENVIRONMENT_PRIORITY:
        if evidence[environment]["recorded"]:
            return environment, evidence[environment]["recorded"]
    return "unknown", {}


def determine_environment(
    events: List[Event],
    environment_columns: Optional[Dict[str, List[str]]] = None,
) -> Tuple[str, Dict[str, str]]:
    """
    Determine the execution environment of a UI activity from its events.

    ``environment_columns`` maps each environment (web, desktop, screen) to the log
    columns that indicate it — identified by the LLM when the log is loaded. The
    environment is the highest-priority one (web > desktop > screen) for which at
    least one event of the activity recorded a value in one of its columns. The
    priority follows the richness of the interface information each environment
    exposes, so the richest available representation decides.

    Args:
        events: The events the UI activity was inferred from
        environment_columns: Indicator columns per environment; None uses
            ``DEFAULT_ENVIRONMENT_COLUMNS``

    Returns:
        (environment, deciding attributes): the environment is "web", "desktop",
        "screen" or "unknown"; the deciding attributes map each indicator column of
        that environment recorded in the events to its first recorded value.
    """
    return richest_environment(environment_evidence(events, environment_columns))


def get_context_from_events(
    events: List[Event],
    environment_columns: Optional[Dict[str, List[str]]] = None,
) -> str:
    """The execution environment of a set of events (see ``determine_environment``).

    Returns:
        Context string: "web", "desktop", "screen", or "unknown"
    """
    return determine_environment(events, environment_columns)[0]
