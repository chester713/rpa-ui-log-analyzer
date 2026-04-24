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

        # Each group produces at least one activity; implicit prerequisites may add more.
        assert len(activities) >= 2

    def test_empty_group_returns_empty_activity(self):
        """Test empty event group returns empty activity."""
        inferrer = ActivityInferrer()
        activity = inferrer.infer_activity([])

        assert activity.name == "Empty"
        assert activity.confidence == 0.0

    def test_mock_infer_web_name_uses_action_target_context(self):
        """Web naming should use Action + Target + Context with readable details."""
        events = [
            Event(
                "click",
                {
                    "application": "Chrome",
                    "tag_name": "button",
                    "element_id": "login-button",
                    "url": "https://example.com/login",
                },
                0,
            )
        ]

        inferrer = ActivityInferrer()
        activity = inferrer.infer_activity(events)

        assert activity.name == "Click button 'login-button' on example.com/login in Chrome"

    def test_mock_infer_desktop_name_uses_spreadsheet_context(self):
        """Desktop naming should include workbook/worksheet/cell_range context when present."""
        events = [
            Event(
                "changeField",
                {
                    "application": "Excel",
                    "workbook": "Q1-Forecast.xlsx",
                    "worksheet": "Inputs",
                    "cell_range": "B2:B4",
                },
                2,
            )
        ]

        inferrer = ActivityInferrer()
        activity = inferrer.infer_activity(events)

        assert (
            activity.name
            == "Write cell range B2:B4 in Excel / workbook Q1-Forecast.xlsx / sheet Inputs"
        )

    def test_parse_response_fallback_avoids_opaque_element_id(self):
        """Opaque IDs should be avoided in inferred names for readability."""
        events = [
            Event(
                "click",
                {
                    "tag_name": "button",
                    "element_id": "6f1f5d9e-b768-4da4-a7f5-cc1c67a8bbaf",
                    "browser_url": "https://portal.example.org/home",
                },
                10,
            )
        ]

        inferrer = ActivityInferrer(llm_client=object())
        activity = inferrer._parse_response("Activity: Unknown activity", events)

        assert activity.name == "Click button element (event row 10) on portal.example.org/home"

    def test_parse_response_fallback_opaque_id_uses_xpath_locator_hint(self):
        """Opaque IDs should include readable xpath-derived hint when available."""
        events = [
            Event(
                "click",
                {
                    "tag_name": "input",
                    "element_id": "b80f58dd-9559-4a90-aaf4-81c001ea6ce2",
                    "xpath": "//table/tbody/tr[3]/td[2]/input[@type='text'][1]",
                    "webpage": "https://portal.example.org/orders",
                },
                99,
            )
        ]

        inferrer = ActivityInferrer(llm_client=object())
        activity = inferrer._parse_response("Activity: Unknown activity", events)

        assert (
            activity.name
            == "Click input 'input type=text #1' (input type=text #1, row 3) on portal.example.org/orders"
        )

    def test_mock_infer_web_name_prefers_url_and_application_context(self):
        """Web names should include readable URL context and browser application."""
        events = [
            Event(
                "write",
                {
                    "tag_type": "textarea",
                    "element_id": "notes",
                    "browser_url": "https://example.com/cases/42",
                    "application": "Edge",
                },
                7,
            )
        ]

        inferrer = ActivityInferrer()
        activity = inferrer.infer_activity(events)

        assert (
            activity.name
            == "Write textarea 'notes' on example.com/cases/42 in Edge"
        )

    def test_post_process_enriches_generic_write_web_label(self):
        """Generic rule-style web label should be enriched to unique readable name."""
        events = [
            Event(
                "paste",
                {
                    "application": "Chrome",
                    "tag_name": "textfield",
                    "element_id": "username",
                    "webpage": "https://example.com/login",
                },
                1,
            )
        ]

        inferrer = ActivityInferrer()
        enriched = inferrer._post_process_inferred_name(
            "Write HTML element on webpage", events
        )

        assert enriched == "Write textfield 'username' on example.com/login in Chrome"
