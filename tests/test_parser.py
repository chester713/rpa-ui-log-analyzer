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
