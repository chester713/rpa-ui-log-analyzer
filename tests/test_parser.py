"""Tests for parser module."""

import pytest
import os
import tempfile
from src.parser.csv_loader import CSVLoader


class _FakeLLM:
    """Picks a fixed event column and reports no context columns.

    Column detection is LLM-driven (no keyword fallback), so loading mechanics
    are tested with a stub that returns deterministic answers for both the
    event-column and context-column prompts.
    """

    def __init__(self, event_column="event"):
        self.event_column = event_column

    def complete(self, prompt):
        if "switch_columns" in prompt or "two column sets" in prompt:
            return '{"switch_columns": [], "group_columns": []}'
        return self.event_column


def _write_csv(text):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write(text)
        return f.name


class TestCSVLoader:
    """Test cases for CSVLoader."""

    def test_load_csv_with_event_column(self):
        """Test loading CSV with event column."""
        path = _write_csv(
            "event,app,url\n"
            "click,Chrome,https://example.com\n"
            "type,Chrome,https://example.com\n"
        )
        try:
            events = CSVLoader(_FakeLLM()).load(path)
            assert len(events) == 2
            assert events[0].event == "click"
            assert events[1].event == "type"
        finally:
            os.unlink(path)

    def test_load_csv_missing_event_column_raises_error(self):
        """Test that an undetectable event column raises ValueError."""
        path = _write_csv("app,url\nChrome,https://example.com\n")
        try:
            # FakeLLM names a column that isn't present, so detection yields None.
            with pytest.raises(ValueError) as exc_info:
                CSVLoader(_FakeLLM()).load(path)
            assert "Missing required column: event" in str(exc_info.value)
        finally:
            os.unlink(path)

    def test_load_csv_with_attributes(self):
        """Test that optional attributes are loaded."""
        path = _write_csv(
            "event,app,webpage,element_id\n"
            "click,Chrome,https://example.com,button1\n"
        )
        try:
            events = CSVLoader(_FakeLLM()).load(path)
            assert len(events) == 1
            assert events[0].attributes["app"] == "Chrome"
            assert events[0].attributes["webpage"] == "https://example.com"
            assert events[0].attributes["element_id"] == "button1"
        finally:
            os.unlink(path)

    def test_empty_csv_returns_no_events(self):
        """Test that a header-only CSV yields zero events."""
        path = _write_csv("event\n")
        try:
            events = CSVLoader(_FakeLLM()).load(path)
            assert len(events) == 0
        finally:
            os.unlink(path)

    def test_load_csv_requires_llm_for_detection(self):
        """Without an LLM, column detection has no fallback and must raise."""
        path = _write_csv("event,app\nclick,Chrome\n")
        try:
            with pytest.raises(ValueError, match="LLM client required"):
                CSVLoader(llm_client=None).load(path)
        finally:
            os.unlink(path)

    def test_llm_response_with_extra_text_is_mapped_to_real_field(self):
        """LLM output with commentary should still resolve to real field name."""

        class FakeLLM:
            def complete(self, _prompt):
                return "The best choice is EventType column."

        loader = CSVLoader(llm_client=FakeLLM())
        fieldnames = ["timestamp", "EventType", "app"]

        detected = loader._detect_event_column_with_llm(fieldnames, sample_rows=[])
        assert detected == "EventType"
