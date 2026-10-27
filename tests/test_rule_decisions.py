"""The workspace shows what the rules decided, and why, as it shows what the LLM decided.

Every explanation is produced by the code that made the decision, never rebuilt afterwards: the
implicit-activity rules record what each rule decided for each activity (``Activity.rule_checks``),
the environment decision reports what the events record for every environment, and a pattern
reports every variant it defines and whether it applies. The web pipeline stores them with each
step, so the pages show the analysis exactly as it was made.
"""

import json
from pathlib import Path

import pytest

from src.inference.activity_inferrer import add_implicit_activities
from src.inference.event_grouper import EventGroup
from src.matching import PATTERNS
from src.matching.pattern_matcher import determine_environment, environment_evidence, richest_environment
from src.models.activity import Activity
from src.models.event import Event
from src.models.pattern import explain_object_type
from src.pipeline.data_pipeline import DataPipeline
from src.web.progressive import _segmentation_summary, build_view, compute_recommendations
from src.web.step_store import StepStore

TEMPLATES = Path(__file__).resolve().parents[1] / "templates"
IMPLICIT_PATTERN = {"switch": "Switch Context", "find": "Find Element", "focus": "Focus"}


def _by_name(name):
    return next(p for p in PATTERNS if p.name == name)


# ── step 4: what each implicit-activity rule decided, and why ────────────────

def _main(i, pattern, target=None, target_id=None):
    return Activity(name=f"A{i}", confidence=0.9, pattern_name=pattern, group_index=i,
                    source_events=[i], target=target, target_id=target_id)


def _group(i, **attributes):
    return EventGroup(events=[Event(f"e{i}", attributes, i)])


def _checks(main):
    return {c["rule"]: c for c in main.rule_checks}


def test_every_rule_records_its_decision_and_reason_for_every_activity() -> None:
    groups = [_group(0, app="Excel"), _group(1, app="Edge"), _group(2, app="Edge")]
    mains = [_main(0, "Read Element", "cell A2", "cell=A2"),
             _main(1, "Focus", "First Name field", "id=f"),
             _main(2, "Write Element", "First Name field", "id=f")]

    add_implicit_activities(groups, mains, ["app"])

    assert all([c["rule"] for c in m.rule_checks] == ["switch", "find", "focus"] for m in mains)
    first, second, third = (_checks(m) for m in mains)
    assert first["switch"]["inserted"] is False
    assert first["switch"]["reason"] == "Excel is the first application recorded in the log, so there is none to switch from."
    assert first["find"]["inserted"] is True
    assert first["focus"] == {"rule": "focus", "inserted": False,
                              "reason": "Only a Write needs its element focused for input."}
    assert second["switch"]["inserted"] is True
    assert second["find"]["inserted"] is True  # the preceding activity is the switch, which targets nothing
    assert third["switch"] == {"rule": "switch", "inserted": False, "reason": "Recorded in Edge, the same application as before."}
    assert third["find"] == {
        "rule": "find", "inserted": False,
        "reason": "Write Element acts on a target element, but the preceding activity (A1) already targets it, "
                  "so it is not located again.",
    }
    assert third["focus"] == {"rule": "focus", "inserted": False,
                              "reason": "The preceding activity (A1) already focuses the element."}


def test_a_check_gives_the_same_reason_as_the_activity_it_inserted() -> None:
    groups = [_group(0, app="Excel"), _group(1, app="Edge")]
    mains = [_main(0, "Read Element", "cell A2", "cell=A2"), _main(1, "Write Element", "First Name field", "id=f")]

    enriched = add_implicit_activities(groups, mains, ["app"])

    for main in mains:
        for check in (c for c in main.rule_checks if c["inserted"]):
            inserted = next(a for a in enriched if a.is_implicit and a.group_index == main.group_index
                            and a.pattern_name == IMPLICIT_PATTERN[check["rule"]])
            assert inserted.reasoning == check["reason"]


def test_the_checks_agree_with_what_was_inserted_for_a_varied_log() -> None:
    groups = [_group(0, app="Excel"), _group(1, app="Edge"), _group(2, app="Edge"), _group(3),
              _group(4, app="Edge"), _group(5, app="Excel"), _group(6, app="Excel")]
    mains = [_main(0, "Read Element", "cell A2", "cell=A2"), _main(1, "Focus", "field", "id=f"),
             _main(2, "Write Element", "field", "id=f"), _main(3, "Scroll"), _main(4, "Open"),
             _main(5, "Write Element", "cell B3", "cell=B3"), _main(6, None)]

    enriched = add_implicit_activities(groups, mains, ["app"])

    inserted = [c["rule"] for m in mains for c in m.rule_checks if c["inserted"]]
    assert [a.pattern_name for a in enriched if a.is_implicit] == [IMPLICIT_PATTERN[r] for r in inserted]


def test_a_missing_application_is_no_evidence_of_a_switch() -> None:
    groups = [_group(0, app="Excel"), _group(1)]
    mains = [_main(0, "Open"), _main(1, "Open")]

    add_implicit_activities(groups, mains, ["app"])

    assert _checks(mains[1])["switch"] == {
        "rule": "switch", "inserted": False,
        "reason": "No application is recorded for this UI activity; a missing value is no evidence of a switch.",
    }


@pytest.mark.parametrize("pattern, target, reason", [
    ("Open", None, "Open does not act on a target element, so it needs no Find."),
    ("Scroll", None, "Scroll acts on the whole page or window here (no target element is named), so it needs no Find."),
    (None, None, "Not covered by the pattern collection, so it is not known to act on a target element."),
])
def test_an_activity_that_acts_on_no_element_needs_no_find(pattern, target, reason) -> None:
    mains = [_main(0, pattern, target)]

    add_implicit_activities([_group(0, app="Edge")], mains, ["app"])

    assert _checks(mains[0])["find"] == {"rule": "find", "inserted": False, "reason": reason}


def test_a_write_after_something_other_than_a_focus_gets_a_focus() -> None:
    mains = [_main(0, "Hover", "cell B3", "cell=B3"), _main(1, "Write Element", "cell B3", "cell=B3")]

    add_implicit_activities([_group(0, app="Excel"), _group(1, app="Excel")], mains, ["app"])

    assert _checks(mains[1])["find"]["inserted"] is False  # the hover already targets the cell
    assert _checks(mains[1])["focus"] == {
        "rule": "focus", "inserted": True,
        "reason": "Writing requires the target element to be focused for input, and the preceding activity does not focus it.",
    }


# ── step 6: what the events record for each environment ──────────────────────

COLUMNS = {"web": ["URL", "Element ID"], "desktop": ["Application", "Workbook"], "screen": ["X", "Y"]}


def test_environment_evidence_reports_what_is_recorded_for_every_environment() -> None:
    events = [Event("click", {"Application": "Edge", "URL": "https://x/", "Element ID": "nan", "X": ""}, 0)]

    evidence = environment_evidence(events, COLUMNS)

    assert evidence == {
        "web": {"checked": ["URL", "Element ID"], "recorded": {"URL": "https://x/"}},
        "desktop": {"checked": ["Application", "Workbook"], "recorded": {"Application": "Edge"}},
        "screen": {"checked": ["X", "Y"], "recorded": {}},  # an empty value and "nan" are not recorded
    }
    assert richest_environment(evidence) == ("web", {"URL": "https://x/"})
    assert determine_environment(events, COLUMNS) == ("web", {"URL": "https://x/"})


def test_the_richest_environment_with_a_recorded_indicator_decides_and_none_means_unknown() -> None:
    desktop = [Event("click", {"Application": "Excel"}, 0)]
    screen = [Event("click", {"X": "10", "Y": "20"}, 0)]
    nothing = [Event("click", {"Timestamp": "t"}, 0)]

    assert determine_environment(desktop, COLUMNS) == ("desktop", {"Application": "Excel"})
    assert determine_environment(screen, COLUMNS) == ("screen", {"X": "10", "Y": "20"})
    assert determine_environment(nothing, COLUMNS) == ("unknown", {})
    assert richest_environment(environment_evidence(nothing, COLUMNS)) == ("unknown", {})


def test_the_object_type_is_explained() -> None:
    assert explain_object_type(_by_name("Write Element"), "web") == (
        "Write Element acts on an element, which in the web environment has the object type HTML element.")
    assert explain_object_type(_by_name("Switch Context"), "desktop") == (
        "Switch Context acts on a context, whatever the environment.")
    assert explain_object_type(_by_name("Write Element"), "unknown") == (
        "The environment is unknown, so the object type is unknown too.")
    assert explain_object_type(None, "web") is None


# ── step 7: which variants of the pattern apply, and why ─────────────────────

def test_every_variant_is_listed_with_its_rank_and_the_reason_it_applies_or_not() -> None:
    write = _by_name("Write Element")

    web = write.describe_methods("web")
    desktop = write.describe_methods("desktop")
    screen = write.describe_methods("screen")

    assert [(v["level"], v["rank"]) for v in web] == [
        ("content-level", 1), ("accessibility-level", 2), ("visual and input level", 3)]
    assert web[0]["why"] == "A web environment has content-level methods of its own."
    assert web[1]["why"] == "Applicable by cumulation: a web object can also be acted on by accessibility-level methods."
    assert [v["rank"] for v in desktop] == [None, 1, 2]
    assert desktop[0]["why"] == "Content-level methods act only on HTML elements, which only a web environment has."
    assert [v["rank"] for v in screen] == [None, None, 1]
    assert screen[1]["why"] == (
        "Accessibility-level methods need the UI Automation tree, which a screen environment does not expose.")


def test_a_pattern_without_a_variant_for_the_environment_says_so_for_every_variant() -> None:
    delete = _by_name("Delete Element")

    assert [(v["applicable"], v["why"]) for v in delete.describe_methods("screen")] == [
        (False, "Delete Element is not defined for the screen environment.")] * 2
    assert {v["why"] for v in delete.describe_methods("unknown")} == {
        "The execution environment is unknown, so no variant can be chosen."}


def test_the_variants_marked_applicable_are_exactly_the_prioritised_methods() -> None:
    for pattern in PATTERNS:
        for environment in ("web", "desktop", "screen", "unknown"):
            ranked = sorted((v for v in pattern.describe_methods(environment) if v["applicable"]),
                            key=lambda v: v["rank"])
            assert [v["method"] for v in ranked] == pattern.get_methods_for_context(environment), (
                pattern.name, environment)


# ── step 5: where each activity's pattern comes from ─────────────────────────

def test_each_match_says_where_its_pattern_comes_from() -> None:
    step1 = {"groups": [{"group_index": 0, "events": [{"event": "e", "row_index": 0, "attributes": {"URL": "u"}}]}],
             "environment_columns": {"web": ["URL"], "desktop": [], "screen": []}}
    step2 = {"activities": [
        {"name": "Find X", "pattern_name": "Find Element", "activity_type": "prerequisite", "is_implicit": True,
         "group_index": 0},
        {"name": "Close", "pattern_name": None, "activity_type": "main", "is_implicit": False, "group_index": 0},
        {"name": "Open", "pattern_name": "Open", "activity_type": "main", "is_implicit": False, "group_index": 0},
    ]}

    records = compute_recommendations(step1, step2)

    assert [r["match_source"] for r in records] == ["rule", "none", "llm"]
    assert records[0]["match_note"] == "Inserted by the Find rule in step 4, which acts through the Find Element pattern."
    assert records[1]["match_note"] == (
        "The LLM found no pattern of the collection that fits this UI activity (step 3), "
        "so nothing is matched and it is not covered.")
    assert records[2]["match_note"] == (
        f"The LLM chose Open for this UI activity in step 3; the pattern's action is {_by_name('Open').action}.")
    assert records[2]["environment_evidence"]["web"] == {"checked": ["URL"], "recorded": {"URL": "u"}}
    assert [v["rank"] for v in records[2]["method_variants"]] == [1, 2, 3]
    assert records[1]["method_variants"] == []  # no pattern, so no variants


# ── step 1: why the log was cut where it was ─────────────────────────────────

def _segment(i, boundary=None, kind=None, attribute=None, rows=(0,)):
    return {"segment_index": i, "rows": list(rows), "labels": [], "boundary": boundary,
            "boundary_kind": kind, "boundary_attribute": attribute}


def _log(*applications):
    return [{"row_index": i, "values": {"Application": a}} for i, a in enumerate(applications)]


def test_the_segmentation_summary_counts_what_started_each_segment_and_missing_applications() -> None:
    segments = [
        _segment(0, rows=(0, 1)),
        _segment(1, "application changed: A → B", "application", rows=(2,)),
        _segment(2, "URL changed: u1 → u2", "data context", "URL", rows=(3,)),
        _segment(3, "URL changed: u2 → u3", "data context", "URL", rows=(4,)),
        _segment(4, "Element ID changed: e1 → e2", "data context", "Element ID", rows=(5,)),
    ]

    summary = _segmentation_summary(segments, _log("A", "", "B", "None", "nan", "B"), ["Application"])

    assert summary == {
        "events": 6, "segments": 5, "application_changes": 1, "context_changes": 3,
        "context_attributes": [["URL", 2], ["Element ID", 1]],
        "no_application": 3,  # "", "None" and "nan" are not recorded
    }


def test_a_log_that_never_changes_context_is_one_segment_without_boundaries() -> None:
    summary = _segmentation_summary([_segment(0, rows=(0, 1))], _log("A", "A"), ["Application"])

    assert (summary["segments"], summary["application_changes"], summary["context_changes"]) == (1, 0, 0)


def test_segments_stored_without_the_reason_kind_leave_the_breakdown_out() -> None:
    segments = [_segment(0), _segment(1, "application changed: A → B", None, rows=(1,))]

    summary = _segmentation_summary(segments, _log("A", "B"), ["Application"])

    assert summary["application_changes"] is None and summary["context_changes"] is None
    assert (summary["events"], summary["segments"]) == (2, 2)


def test_no_application_attribute_means_no_missing_application_count() -> None:
    assert _segmentation_summary([_segment(0)], _log("A"), [])["no_application"] is None


# ── the CLI carries the same decisions ───────────────────────────────────────

_FILL_FORM = (
    "Event,Application,Workbook,Cell range,Element ID,URL\n"
    "Get Cell,Microsoft Excel,challenge.xlsx,A2,,\n"
    "clickTextField,Edge,,,lPupZ,https://rpachallenge.com/\n"
    "Paste,Edge,,,,https://rpachallenge.com/\n"
    "changeField,Edge,,,lPupZ,https://rpachallenge.com/\n"
)


class _FillFormLLM:
    def complete(self, prompt):
        if "selecting the activity-name attribute" in prompt:
            return "Event"
        if '"environment_attributes"' in prompt:
            return json.dumps({
                "switch_attributes": ["Application"], "group_attributes": ["Application", "Workbook", "URL"],
                "environment_attributes": {"web": ["URL", "Element ID"],
                                           "desktop": ["Application", "Workbook", "Cell range"], "screen": []},
                "element_attributes": ["Element ID", "Cell range"],
            })
        if "grouping UI events into UI activities" in prompt:
            return json.dumps([[0], [1], [2, 3]])
        if "RPA (Robotic Process Automation) designer" in prompt:
            return json.dumps([
                {"activity_name": "Read cell A2", "pattern": "Read Element", "target": "cell A2"},
                {"activity_name": "Focus First Name field", "pattern": "Focus", "target": "First Name field"},
                {"activity_name": "Write First Name field", "pattern": "Write Element", "target": "First Name field"},
            ])
        raise AssertionError("unexpected prompt: " + prompt[:80])


def test_cli_json_carries_the_rule_checks_the_environment_evidence_and_the_variants(tmp_path) -> None:
    path = tmp_path / "fill.csv"
    path.write_text(_FILL_FORM, encoding="utf-8")

    result = DataPipeline(str(path), llm_client=_FillFormLLM()).run().to_dict()

    assert [[(c["rule"], c["inserted"]) for c in a["rule_checks"]] for a in result["activities"]] == [
        [("switch", False), ("find", True), ("focus", False)],
        [("switch", True), ("find", True), ("focus", False)],
        [("switch", False), ("find", False), ("focus", False)],
    ]
    by_name = {r["inferred_activity"]: r for r in result["recommendations"]}
    write = by_name["Write First Name field"]
    assert write["environment_evidence"]["web"]["recorded"] == {"URL": "https://rpachallenge.com/", "Element ID": "lPupZ"}
    assert write["environment_evidence"]["desktop"]["recorded"] == {"Application": "Edge"}
    assert [v["rank"] for v in write["method_variants"]] == [1, 2, 3]
    switch = next(r for r in result["recommendations"] if r["context_switch"])
    assert switch["execution_environment"] == "desktop" and switch["environment_evidence"] is None


# ── analyses stored before the explanations existed still open ───────────────

def test_an_analysis_stored_without_the_explanations_still_builds_its_view(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("src.web.step_store._STORE_DIR", str(tmp_path / "progressive"))
    log = tmp_path / "log.csv"
    log.write_text("Event,Application,URL\nclick,Edge,https://x/\n", encoding="utf-8")
    store = StepStore("a1")
    store.save("meta", {"aid": "a1", "history_id": "h1", "filename": "log.csv", "filepath": str(log),
                        "event_column": "Event", "llm_column": "Event"})
    store.save_step(1, {
        "segments": [{"segment_index": 0, "rows": [0], "labels": ["click"], "boundary": None}],
        "groups": [{"group_index": 0, "events": [{"event": "click", "row_index": 0, "attributes": {}}]}],
        "application_attributes": ["Application"], "environment_columns": {"web": ["URL"], "desktop": [], "screen": []},
    })
    store.save_step(2, {"activities": [
        {"name": "Activate OK", "confidence": 0.9, "evidence": [], "reasoning": "", "source_events": [0],
         "activity_type": "main", "is_implicit": False, "group_index": 0, "pattern_name": "Activate",
         "target": "OK", "target_id": None, "context": None},
    ]})
    store.save_step(3, {"recommendations": [
        {"pattern": "Activate", "action": "Activate", "category": "Control", "pattern_description": "d",
         "object_type": "HTML element", "environment": "web", "deciding": {"URL": "https://x/"},
         "environment_note": None, "methods": ["DOM manipulation"], "method": "DOM manipulation", "method_note": None},
    ]})

    view = build_view(store)

    assert view["activities"][0]["rule_checks"] == []
    assert view["matching"] is None  # nothing says where the pattern came from
    assert (view["segmentation"]["events"], view["segmentation"]["segments"]) == (1, 1)
    assert view["implicit_rules"] == {"checked": 1, "switch": 0, "find": 0, "focus": 0}
    assert view["environments"] == {"web": 1, "desktop": 0, "screen": 0, "unknown": 0}
    assert view["recommendation"] == {"activities": 1, "with_method": 1, "not_covered": 0,
                                      "unknown_environment": 0, "no_variant": 0}


# ── what the rules and the lookup show is escaped ────────────────────────────

def test_workspace_escapes_every_rule_and_lookup_value_it_shows() -> None:
    template = (TEMPLATES / "workspace.html").read_text(encoding="utf-8")

    for escaped in (
        "esc(c.reason)",
        "esc(a.match_note)",
        "esc(text)",
        "esc(e.checked.join(', '))",
        "${esc(k)} = ${esc(String(v).slice(0, 60))}",
        "esc(a.environment_note)",
        "esc(a.object_type_note)",
        "esc(v.method)",
        "esc(v.why)",
        "esc(a.method_note || 'No method.')",
        "esc(name)} ${n}×",
    ):
        assert escaped in template
