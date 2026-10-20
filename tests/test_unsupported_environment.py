"""A pattern with no variant for the detected environment is kept, and the reason is reported.

Pattern matching is by name only. Whether the pattern can be carried out in the
activity's execution environment is decided when the method is chosen: if the
pattern defines no variant there (e.g. Delete Element on screen, because an
element cannot be deleted from an image) the activity keeps its pattern, gets no
method, and says why. Web (progressive) and CLI pipelines report the same note.
"""

from pathlib import Path

import pytest

import app as webapp
from src.inference.event_grouper import EventGroup
from src.matching import PATTERNS, PatternMatcher
from src.models.activity import Activity
from src.models.event import Event
from src.models.pattern import explain_missing_method
from src.pipeline.data_pipeline import DataPipeline, PipelineResult

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"
DELETE_SCREEN_NOTE = (
    "No method for the screen environment: Delete Element has no screen variant "
    "(an element cannot be deleted from an image)."
)


def _pattern(name: str):
    return next(p for p in PATTERNS if p.name == name)


# ── pattern files ───────────────────────────────────────────────────────────

def test_delete_element_records_why_it_has_no_screen_variant() -> None:
    assert _pattern("Delete Element").unsupported_reasons == {
        "screen": "an element cannot be deleted from an image"
    }


def test_other_patterns_declare_no_unsupported_reasons() -> None:
    assert all(not p.unsupported_reasons for p in PATTERNS if p.name != "Delete Element")


# ── matcher ─────────────────────────────────────────────────────────────────

def test_matcher_resolves_by_name_only_whatever_the_environment() -> None:
    matcher = PatternMatcher(PATTERNS)
    activity = Activity(name="Delete icon", confidence=0.9, pattern_name="  delete element ")

    assert matcher.match(activity).name == "Delete Element"


@pytest.mark.parametrize("pattern_name", [None, "", "Teleport Element"])
def test_matcher_returns_none_for_missing_or_unknown_names(pattern_name) -> None:
    activity = Activity(name="Something", confidence=0.9, pattern_name=pattern_name)

    assert PatternMatcher(PATTERNS).match(activity) is None


# ── explanation messages ────────────────────────────────────────────────────

def test_explanation_for_pattern_without_a_variant_includes_the_reason() -> None:
    assert explain_missing_method(_pattern("Delete Element"), "screen") == DELETE_SCREEN_NOTE


def test_explanation_without_a_recorded_reason_still_names_the_missing_variant() -> None:
    assert explain_missing_method(_pattern("Switch Context"), "web") == (
        "No method for the web environment: Switch Context has no web variant."
    )


def test_no_explanation_when_a_method_exists() -> None:
    assert explain_missing_method(_pattern("Delete Element"), "web") is None
    assert explain_missing_method(_pattern("Delete Element"), "desktop") is None


def test_explanation_when_the_environment_is_unknown() -> None:
    note = explain_missing_method(_pattern("Activate"), "unknown")

    assert "could not be determined" in note


def test_explanation_when_no_pattern_matched() -> None:
    assert "no pattern matched" in explain_missing_method(None, "web")


# ── CLI pipeline ────────────────────────────────────────────────────────────

def _recommendations(activities, groups):
    return DataPipeline("unused.csv", llm_client=None)._create_recommendations(activities, groups)


def test_cli_recommendation_keeps_pattern_and_reports_note() -> None:
    groups = [EventGroup(events=[Event("delete", {"x": "10", "y": "20"}, 0)])]
    activities = [Activity(name="Delete icon", confidence=0.9, group_index=0, pattern_name="Delete Element")]

    (rec,) = _recommendations(activities, groups)

    assert rec.execution_environment == "screen"
    assert rec.pattern.name == "Delete Element"
    assert rec.activity_action == "Delete"
    assert rec.method is None
    assert rec.method_note == DELETE_SCREEN_NOTE
    assert rec.to_dict()["method_note"] == DELETE_SCREEN_NOTE

    summary = PipelineResult([], [], [rec], {}).summary()
    assert "Delete icon -> no method (screen)" in summary
    assert DELETE_SCREEN_NOTE in summary


def test_cli_recommendation_has_no_note_when_a_method_exists() -> None:
    groups = [EventGroup(events=[Event("click", {"app": "Excel"}, 0)])]
    activities = [Activity(name="Delete row", confidence=0.9, group_index=0, pattern_name="Delete Element")]

    (rec,) = _recommendations(activities, groups)

    assert rec.method == "UI Automation manipulation"
    assert rec.method_note is None


def test_cli_context_switch_still_uses_the_desktop_method() -> None:
    groups = [EventGroup(events=[Event("open", {"browser_url": "https://example.test"}, 0)])]
    activities = [
        Activity(
            name="Switch context from Excel to Chrome",
            confidence=1.0,
            activity_type="context_switch",
            is_implicit=True,
            group_index=0,
            pattern_name="Switch Context",
        )
    ]

    (rec,) = _recommendations(activities, groups)

    assert rec.execution_environment == "desktop"
    assert rec.method == "UI Automation manipulation"
    assert rec.method_note is None


# ── web (progressive) pipeline ──────────────────────────────────────────────

def _activity(name, pattern_name, group_index=0, activity_type="main"):
    return {
        "name": name,
        "confidence": 0.9,
        "evidence": [],
        "reasoning": "",
        "source_events": [group_index],
        "activity_type": activity_type,
        "is_implicit": activity_type != "main",
        "group_index": group_index,
        "pattern_name": pattern_name,
    }


def _group(index, attributes):
    return {
        "group_index": index,
        "events": [{"event": "do", "row_index": index, "attributes": attributes}],
        "is_context_switch": False,
        "previous_app": None,
        "current_app": None,
    }


def _run_pipeline(monkeypatch, tmp_path, groups, activities):
    """Steps 5 to 7 of the web pipeline for stored UI activities (no model call)."""
    from src.web.progressive import compute_recommendations

    step1 = {"groups": groups, "environment_columns": None}
    return compute_recommendations(step1, {"activities": activities})


def test_web_delete_element_on_screen_keeps_pattern_and_explains_missing_method(monkeypatch, tmp_path) -> None:
    (rec,) = _run_pipeline(
        monkeypatch, tmp_path,
        groups=[_group(0, {"x": "10", "y": "20"})],
        activities=[_activity("Delete icon", "Delete Element")],
    )

    assert rec["pattern"] == "Delete Element"
    assert rec["action"] == "Delete"
    assert rec["environment"] == "screen"
    assert rec["object_type"] == "visual element"
    assert rec["method"] is None
    assert rec["method_note"] == DELETE_SCREEN_NOTE


def test_web_delete_element_on_desktop_still_gets_a_method(monkeypatch, tmp_path) -> None:
    (rec,) = _run_pipeline(
        monkeypatch, tmp_path,
        groups=[_group(0, {"application": "Excel"})],
        activities=[_activity("Delete row", "Delete Element")],
    )

    assert rec["method"] == "UI Automation manipulation"
    assert rec["method_note"] is None


def test_web_unknown_environment_keeps_pattern_and_says_environment_is_unknown(monkeypatch, tmp_path) -> None:
    (rec,) = _run_pipeline(
        monkeypatch, tmp_path,
        groups=[_group(0, {})],
        activities=[_activity("Activate button", "Activate")],
    )

    assert rec["pattern"] == "Activate"
    assert rec["environment"] == "unknown"
    assert rec["method"] is None
    assert "could not be determined" in rec["method_note"]


def test_web_unknown_pattern_name_is_reported_as_no_pattern(monkeypatch, tmp_path) -> None:
    (rec,) = _run_pipeline(
        monkeypatch, tmp_path,
        groups=[_group(0, {"application": "Excel"})],
        activities=[_activity("Drag file to folder", None)],
    )

    assert rec["pattern"] is None
    assert rec["method"] is None
    assert "not covered by the pattern collection" in rec["method_note"]


def test_web_context_switch_takes_the_desktop_environment(monkeypatch, tmp_path) -> None:
    (rec,) = _run_pipeline(
        monkeypatch, tmp_path,
        groups=[_group(0, {"browser_url": "https://example.test"})],
        activities=[_activity("Switch context from Excel to Chrome", "Switch Context",
                              activity_type="context_switch")],
    )

    assert rec["environment"] == "desktop"
    assert rec["object_type"] == "Context"
    assert rec["methods"] == ["UI Automation manipulation", "Hardware simulation"]
    assert rec["method_note"] is None
    assert "operation of the desktop" in rec["environment_note"]


# ── templates ───────────────────────────────────────────────────────────────

def test_results_template_explains_missing_method() -> None:
    template = (TEMPLATE_DIR / "results.html").read_text(encoding="utf-8")

    assert "a.method_note" in template
    assert "textContent = a.method_note" in template  # inserted as text, never as HTML


def test_workspace_template_shows_method_notes() -> None:
    template = (TEMPLATE_DIR / "workspace.html").read_text(encoding="utf-8")

    assert "esc(a.method_note" in template
