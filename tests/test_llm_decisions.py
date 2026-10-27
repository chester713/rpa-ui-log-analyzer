"""The workspace shows what the LLM decided, not only which prompt ran.

P1 and P2 return no reasons, so step 1 states the activity-name attribute and the role the LLM
gave every attribute of the log. P3 returns only runs of events, so step 2 states what the LLM
did with each rule-based segment: kept it, divided it, or combined it with its neighbour. P4
returns its own reasoning and evidence, which step 3 shows. Nothing is explained after the
fact: where a prompt gave no reason, none is shown.
"""

import json
import sys
from pathlib import Path

import pytest

import src_cli
from src.pipeline.data_pipeline import DataPipeline
from src.web.progressive import _abstraction_decisions, _attribute_roles, build_view
from src.web.step_store import StepStore

TEMPLATES = Path(__file__).resolve().parents[1] / "templates"


# ── step 2 (P3): kept, divided or combined ───────────────────────────────────

def _segments(*boundaries):
    return [{"segment_index": i, "rows": [], "labels": [], "boundary": b} for i, b in enumerate(boundaries)]


def _ui_activities(*touched):
    return [{"index": i, "segments": list(t)} for i, t in enumerate(touched)]


def test_a_segment_is_kept_divided_or_combined_with_its_neighbour() -> None:
    segments = _segments(None, "application changed: Excel → Edge", "application changed: Edge → Excel",
                         "webpage changed: a → b")
    ui_activities = _ui_activities([0], [1], [1], [2, 3])

    decisions, counts = _abstraction_decisions(segments, ui_activities)

    assert [(d["kind"], d["note"]) for d in decisions] == [
        ("kept", "Kept segment S1 as one UI activity"),
        ("divided", "Divided segment S2: part 1 of 2"),
        ("divided", "Divided segment S2: part 2 of 2"),
        ("combined", "Combined events of S3 and S4; the rules had split them (webpage changed: a → b)"),
    ]
    assert counts == {"segments": 4, "ui_activities": 4, "kept": 1, "divided": 1, "combined": 1}


def test_combining_three_segments_names_each_and_every_boundary_crossed() -> None:
    segments = _segments(None, "x changed: 1 → 2", "y changed: 3 → 4")

    decisions, counts = _abstraction_decisions(segments, _ui_activities([0, 1, 2]))

    assert decisions[0]["note"] == "Combined events of S1, S2 and S3; the rules had split them (x changed: 1 → 2; y changed: 3 → 4)"
    assert counts["combined"] == 2 and counts["kept"] == 0 and counts["divided"] == 0


def test_a_divided_segment_can_also_be_combined_with_the_next_one() -> None:
    segments = _segments(None, "application changed: A → B")

    decisions, counts = _abstraction_decisions(segments, _ui_activities([0], [0, 1], [1]))

    assert [d["note"] for d in decisions] == [
        "Divided segment S1: part 1 of 2",
        "Combined events of S1 and S2; the rules had split them (application changed: A → B)",
        "Divided segment S2: part 2 of 2",
    ]
    assert counts == {"segments": 2, "ui_activities": 3, "kept": 0, "divided": 2, "combined": 1}


# ── step 1 (P1, P2): the role of every attribute ─────────────────────────────

def _rows(*values):
    return [{"row_index": i, "values": v} for i, v in enumerate(values)]


def test_every_attribute_is_listed_with_its_roles_and_example_values() -> None:
    columns = ["Event", "Application", "Element ID", "Timestamp"]
    rows = _rows(
        {"Event": "click", "Application": "Excel", "Element ID": "", "Timestamp": "t1"},
        {"Event": "paste", "Application": "Excel", "Element ID": "x1", "Timestamp": "t2"},
        {"Event": "click", "Application": "Edge", "Element ID": "x2", "Timestamp": "t3"},
    )
    step1 = {
        "application_attributes": ["Application"], "context_attributes": [], "element_columns": ["Element ID"],
        "environment_columns": {"web": ["Element ID"], "desktop": ["Application"], "screen": []},
    }

    table = {a["name"]: a for a in _attribute_roles(columns, rows, step1, "Event")}

    assert list(table) == columns
    assert table["Event"]["roles"] == ["Activity name (P1)"]
    assert table["Application"]["roles"] == ["Application (software context)", "Desktop indicator"]
    assert table["Element ID"]["roles"] == ["Target element", "Web indicator"]
    assert table["Timestamp"]["roles"] == []  # the LLM gave it no role
    assert table["Application"]["examples"] == ["Excel", "Edge"]  # distinct, in the order recorded
    assert table["Element ID"]["examples"] == ["x1", "x2"]  # an empty value is no example


def test_examples_are_three_distinct_values_and_a_long_one_is_clipped() -> None:
    long_value = "https://example.com/" + "a" * 60
    rows = _rows(*[{"URL": v} for v in ["u1", "u1", "u2", long_value, "u4"]])

    [url] = _attribute_roles(["URL"], rows, {}, None)

    assert url["examples"][:2] == ["u1", "u2"]
    assert len(url["examples"]) == 3
    assert url["examples"][2].endswith("…") and len(url["examples"][2]) == 40


def test_the_roles_are_listed_even_when_the_uploaded_file_is_gone() -> None:
    step1 = {"application_attributes": ["Application"], "element_columns": ["Element ID"]}

    table = _attribute_roles([], [], step1, "Event")

    assert [(a["name"], a["roles"], a["examples"]) for a in table] == [
        ("Event", ["Activity name (P1)"], []),
        ("Application", ["Application (software context)"], []),
        ("Element ID", ["Target element"], []),
    ]


@pytest.mark.parametrize("llm_column, source", [
    ("Event", "proposed by the LLM, confirmed by the analyst"),
    ("Application", "selected by the analyst; the LLM had proposed Application"),
    ("", "selected by the analyst; the LLM did not propose an attribute of the log"),
])
def test_the_activity_name_attribute_says_who_chose_it(monkeypatch, tmp_path, llm_column, source) -> None:
    monkeypatch.setattr("src.web.step_store._STORE_DIR", str(tmp_path / "progressive"))
    log = tmp_path / "log.csv"
    log.write_text("Event,Application\nclick,Excel\n", encoding="utf-8")
    store = StepStore("a1")
    store.save("meta", {"aid": "a1", "history_id": "h1", "filename": "log.csv", "filepath": str(log),
                        "event_column": "Event", "llm_column": llm_column})
    store.save_step(1, {
        "segments": [{"segment_index": 0, "rows": [0], "labels": ["click"], "boundary": None}],
        "groups": [{"group_index": 0, "events": [{"event": "click", "row_index": 0, "attributes": {}}]}],
        "application_attributes": ["Application"],
    })

    roles = build_view(store)["roles"]

    assert roles["event_column_source"] == source
    assert [a["name"] for a in roles["attributes"]] == ["Event", "Application"]


# ── the CLI carries the same decisions ───────────────────────────────────────

_FILL_FORM = (
    "Event,Application,Workbook,Cell range,Element ID,URL\n"
    "Get Cell,Microsoft Excel,challenge.xlsx,A2,,\n"
    "clickTextField,Edge,,,lPupZ,https://rpachallenge.com/\n"
    "Paste,Edge,,,,https://rpachallenge.com/\n"
    "changeField,Edge,,,lPupZ,https://rpachallenge.com/\n"
)


class _FillFormLLM:
    """Answers P1 to P4 for the Fill Form snippet, with a reasoning for every UI activity."""

    def complete(self, prompt):
        if "selecting the activity-name attribute" in prompt:
            return "Event"
        if '"environment_attributes"' in prompt:
            return json.dumps({
                "switch_attributes": ["Application"],
                "group_attributes": ["Application", "Workbook", "URL"],
                "environment_attributes": {"web": ["URL", "Element ID"],
                                           "desktop": ["Application", "Workbook", "Cell range"], "screen": []},
                "element_attributes": ["Element ID", "Cell range"],
            })
        if "grouping UI events into UI activities" in prompt:
            return json.dumps([[0], [1], [2, 3]])
        if "RPA (Robotic Process Automation) designer" in prompt:
            return json.dumps([
                {"activity_name": "Read cell A2", "pattern": "Read Element", "target": "cell A2",
                 "evidence": ["Get Cell in Excel"], "confidence": 0.9, "reasoning": "A cell is read from the workbook."},
                {"activity_name": "Focus First Name field", "pattern": "Focus", "target": "First Name field",
                 "evidence": ["click on a text field"], "confidence": 0.8, "reasoning": "Clicking a text field focuses it."},
                {"activity_name": "Write First Name field", "pattern": "Write Element", "target": "First Name field",
                 "evidence": ["Paste", "changeField"], "confidence": 0.9, "reasoning": "The value is pasted into the field."},
            ])
        raise AssertionError("unexpected prompt: " + prompt[:80])


def test_cli_json_carries_the_reasoning_and_the_attribute_roles(tmp_path) -> None:
    path = tmp_path / "fill.csv"
    path.write_text(_FILL_FORM, encoding="utf-8")

    result = DataPipeline(str(path), llm_client=_FillFormLLM()).run().to_dict()

    assert [a["reasoning"] for a in result["activities"]] == [
        "A cell is read from the workbook.", "Clicking a text field focuses it.", "The value is pasted into the field.",
    ]
    assert result["statistics"]["attribute_roles"] == {
        "activity_name": "Event",
        "application": ["Application"],
        "data_context": ["Workbook", "URL"],
        "element": ["Element ID", "Cell range"],
        "environment": {"web": ["URL", "Element ID"], "desktop": ["Application", "Workbook", "Cell range"], "screen": []},
    }


def test_cli_verbose_prints_the_attribute_roles_and_the_reasoning(monkeypatch, tmp_path, capsys) -> None:
    path = tmp_path / "fill.csv"
    path.write_text(_FILL_FORM, encoding="utf-8")
    monkeypatch.setattr(src_cli, "get_llm_client", lambda: _FillFormLLM())
    monkeypatch.setattr(sys, "argv", ["src_cli.py", str(path), "--verbose"])

    with pytest.raises(SystemExit) as finished:
        src_cli.main()

    out = capsys.readouterr().out
    assert finished.value.code == 0
    assert "=== Attribute Roles (identified by the LLM) ===" in out
    assert "  Activity name: Event" in out
    assert "  Data context: Workbook, URL" in out
    assert "  Screen indicators: none" in out
    assert "  Reasoning: Clicking a text field focuses it." in out


# ── LLM text is escaped where it is shown ────────────────────────────────────

def test_workspace_escapes_every_llm_and_log_value_it_shows() -> None:
    template = (TEMPLATES / "workspace.html").read_text(encoding="utf-8")

    for escaped in (
        "esc(a.reasoning)",
        "a.evidence.map(e => `<li>${esc(e)}</li>`)",
        "esc(u.decision.note)",
        "esc(roles.event_column_source)",
        "esc(a.name)",
        "a.roles.map(r => `<span class=\"chip\">${esc(r)}</span>`)",
        "esc(a.examples.join(' · '))",
    ):
        assert escaped in template


def test_results_page_shows_the_llm_reasoning_as_text() -> None:
    template = (TEMPLATES / "results.html").read_text(encoding="utf-8")

    assert 'id="dLlmReason"' in template
    assert "getElementById('dLlmReason').textContent = a.reasoning" in template
