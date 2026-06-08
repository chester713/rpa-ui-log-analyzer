"""Tests for inference module."""

import pytest
from src.models.event import Event
from src.inference.event_grouper import EventGrouper
from src.inference.activity_inferrer import ActivityInferrer


class TestEventGrouper:
    """Test cases for EventGrouper."""

    def test_group_events_with_same_app(self):
        """Test grouping events with same app attribute."""
        events = [
            Event("click", {"app": "Chrome", "element": "button1"}, 0),
            Event("type", {"app": "Chrome", "element": "input1"}, 1),
            Event("submit", {"app": "Chrome", "element": "button1"}, 2),
        ]

        grouper = EventGrouper()
        groups = grouper.group_events(events)

        assert len(groups) == 1
        assert len(groups[0]) == 3

    def test_group_events_different_apps(self):
        """Test events with different apps are separate groups."""
        events = [
            Event("click", {"app": "Chrome"}, 0),
            Event("click", {"app": "Excel"}, 1),
        ]

        grouper = EventGrouper()
        groups = grouper.group_events(events)

        assert len(groups) == 2

    def test_group_events_with_same_webpage(self):
        """Test grouping by webpage attribute."""
        events = [
            Event("click", {"webpage": "https://example.com/login"}, 0),
            Event("type", {"webpage": "https://example.com/login"}, 1),
            Event("click", {"webpage": "https://example.com/home"}, 2),
        ]

        grouper = EventGrouper()
        groups = grouper.group_events(events)

        assert len(groups) == 2
        assert len(groups[0]) == 2
        assert len(groups[1]) == 1

    def test_empty_events_returns_empty(self):
        """Test empty event list returns empty groups."""
        grouper = EventGrouper()
        groups = grouper.group_events([])
        assert groups == []

    def test_single_event_creates_single_group(self):
        """Test single event creates one group."""
        events = [Event("click", {"app": "Chrome"}, 0)]

        grouper = EventGrouper()
        groups = grouper.group_events(events)

        assert len(groups) == 1
        assert len(groups[0]) == 1


class _FakeLLM:
    """Returns a fixed batch JSON array, mimicking the activity-naming LLM."""

    def __init__(self, activity_name="Activate login button", pattern="Activate"):
        self.activity_name = activity_name
        self.pattern = pattern

    def complete(self, _prompt):
        return (
            '[{"activity_name": "%s", "pattern": "%s", '
            '"context_switch": {"detected": false, "from_context": null, "to_context": null}, '
            '"prerequisite": {"needed": false}, '
            '"evidence": ["clicked the button"], "confidence": 0.9, '
            '"reasoning": "user activated the button"}]'
            % (self.activity_name, self.pattern)
        )


class TestActivityInferrer:
    """Test cases for ActivityInferrer (LLM-driven; no heuristic fallback)."""

    def test_empty_group_returns_empty_activity(self):
        """Test empty event group returns empty activity."""
        inferrer = ActivityInferrer()
        activity = inferrer.infer_activity([])

        assert activity.name == "Empty"
        assert activity.confidence == 0.0

    def test_infer_activities_requires_llm(self):
        """Without an LLM there is no fallback — inference must raise."""
        groups = [[Event("click", {"app": "Chrome"}, 0)]]

        inferrer = ActivityInferrer()  # no llm_client
        with pytest.raises(ValueError, match="LLM client required"):
            inferrer.infer_activities(groups)

    def test_infer_activities_uses_llm_supplied_name_and_pattern(self):
        """Activity name and pattern come straight from the LLM response."""
        groups = [[Event("click", {"app": "Chrome", "element": "login"}, 0)]]

        inferrer = ActivityInferrer(llm_client=_FakeLLM())
        activities = inferrer.infer_activities(groups)

        assert len(activities) >= 1
        main = activities[-1]
        assert main.name == "Activate login button"
        assert main.pattern_name == "Activate"
