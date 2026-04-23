"""Tests for parser module."""

import pytest
import os
import tempfile
from src.parser.csv_loader import CSVLoader, load_csv


class TestCSVLoader:
    """Test cases for CSVLoader."""

    def test_load_csv_with_required_column(self):
        """Test loading CSV with event column."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("event,app,url\n")
            f.write("click,Chrome,https://example.com\n")
            f.write("type,Chrome,https://example.com\n")
            temp_path = f.name

        try:
            events = load_csv(temp_path)
            assert len(events) == 2
            assert events[0].event == "click"
            assert events[1].event == "type"
        finally:
            os.unlink(temp_path)

    def test_load_csv_missing_required_column_raises_error(self):
        """Test that missing event column raises ValueError."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("app,url\n")
            f.write("Chrome,https://example.com\n")
            temp_path = f.name

        try:
            with pytest.raises(ValueError) as exc_info:
                load_csv(temp_path)
            assert "Missing required column: event" in str(exc_info.value)
        finally:
            os.unlink(temp_path)

    def test_load_csv_with_attributes(self):
        """Test that optional attributes are loaded."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("event,app,webpage,element_id\n")
            f.write("click,Chrome,https://example.com,button1\n")
            temp_path = f.name

        try:
            events = load_csv(temp_path)
            assert len(events) == 1
            assert events[0].attributes["app"] == "Chrome"
            assert events[0].attributes["webpage"] == "https://example.com"
            assert events[0].attributes["element_id"] == "button1"
        finally:
            os.unlink(temp_path)

    def test_empty_csv_raises_error(self):
        """Test that empty CSV raises appropriate error."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("event\n")
            temp_path = f.name

        try:
            events = load_csv(temp_path)
            assert len(events) == 0
        finally:
            os.unlink(temp_path)

    def test_fallback_prefers_verb_noun_like_column_values(self):
        """Fallback should choose column with action-like event values."""
        loader = CSVLoader(llm_client=None)
        fieldnames = ["timestamp", "action_name", "application"]
        sample_rows = [
            {
                "timestamp": "2026-04-23 10:00:01",
                "action_name": "activateWorkbook",
                "application": "Excel",
            },
            {
                "timestamp": "2026-04-23 10:00:03",
                "action_name": "openWindow",
                "application": "Chrome",
            },
            {
                "timestamp": "2026-04-23 10:00:07",
                "action_name": "clickTextField",
                "application": "Chrome",
            },
        ]

        detected = loader._detect_event_column_fallback(fieldnames, sample_rows)
        assert detected == "action_name"

    def test_llm_response_with_extra_text_is_mapped_to_real_field(self):
        """LLM output with commentary should still resolve to real field name."""

        class FakeLLM:
            def complete(self, _prompt):
                return "The best choice is EventType column."

        loader = CSVLoader(llm_client=FakeLLM())
        fieldnames = ["timestamp", "EventType", "app"]

        detected = loader._detect_event_column_with_llm(fieldnames, sample_rows=[])
        assert detected == "EventType"

    def test_llm_bad_pick_is_overridden_by_stronger_value_pattern(self):
        """If LLM picks weak column, detector should prefer action-like values."""

        class FakeLLM:
            def complete(self, _prompt):
                return "title"

        loader = CSVLoader(llm_client=FakeLLM())
        fieldnames = ["title", "concept:name", "timestamp"]
        sample_rows = [
            {
                "title": "",
                "concept:name": "activateWorkbook",
                "timestamp": "2026-01-23T12:57:07.193",
            },
            {
                "title": "",
                "concept:name": "openWindow",
                "timestamp": "2026-01-23T12:57:07.490",
            },
            {
                "title": "",
                "concept:name": "clickTextField",
                "timestamp": "2026-01-23T12:59:01.159",
            },
        ]

        detected = loader._detect_event_column_with_llm(
            fieldnames, sample_rows=sample_rows
        )
        assert detected == "concept:name"
