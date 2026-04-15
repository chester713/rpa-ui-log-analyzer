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


class TestActivityInferrer:
    """Test cases for ActivityInferrer."""

    def test_infer_activity_returns_activity(self):
        """Test that infer_activity returns Activity object."""
        events = [
            Event("click", {"app": "Chrome", "element": "button"}, 0),
            Event("type", {"app": "Chrome", "element": "input"}, 1),
        ]

        inferrer = ActivityInferrer()
        activity = inferrer.infer_activity(events)

        assert activity.name is not None
        assert 0.0 <= activity.confidence <= 1.0
        assert isinstance(activity.evidence, list)

    def test_infer_activities_multiple_groups(self):
        """Test inferring activities for multiple groups."""
        groups = [
            [Event("click", {"app": "Chrome"}, 0)],
            [Event("type", {"app": "Excel"}, 1)],
        ]

        inferrer = ActivityInferrer()
        activities = inferrer.infer_activities(groups)

        assert len(activities) == 2

    def test_empty_group_returns_empty_activity(self):
        """Test empty event group returns empty activity."""
        inferrer = ActivityInferrer()
        activity = inferrer.infer_activity([])

        assert activity.name == "Empty"
        assert activity.confidence == 0.0
