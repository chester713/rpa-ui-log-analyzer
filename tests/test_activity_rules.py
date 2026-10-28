"""UI activity abstraction, rule-based implicit activities, object types and coverage.

* The refinement LLM returns runs of consecutive event numbers, so a context segment
  can be divided (focusing a field vs writing into it) as well as combined.
* Implicit activities follow fixed rules, applied in the order Switch context ->
  Find -> Focus: an element is found, then focused, then written to.
* Object types follow the execution environment; a pattern may be "not covered".
"""

import json
import re

import pytest

from src.inference.activity_inferrer import ActivityInferrer, add_implicit_activities
from src.inference.event_grouper import EventGroup, EventGrouper, LLMGroupRefiner
from src.matching import PATTERNS
from src.models.activity import Activity
from src.models.event import Event
from src.models.pattern import explain_missing_method, object_type_for
from src.parser.csv_loader import CSVLoader
from src.pipeline.data_pipeline import DataPipeline


def _by_name(name):
    return next(p for p in PATTERNS if p.name == name)


# ── refinement: divide and combine ──────────────────────────────────────────

class _Runs:
    def __init__(self, runs):
        self.runs = runs
        self.prompts = []

    def complete(self, prompt):
        self.prompts.append(prompt)
        return json.dumps(self.runs)


def _fill_form_events():
    return [
        Event("clickTextField", {"app": "Edge", "element_id": "lPupZ", "url": "u"}, 1),
        Event("Paste", {"app": "Edge", "url": "u"}, 2),
        Event("changeField", {"app": "Edge", "element_id": "lPupZ", "url": "u"}, 3),
    ]


def test_refinement_can_divide_a_context_segment() -> None:
    groups = EventGrouper().group_events_with_context_switches(_fill_form_events())
    assert len(groups) == 1  # all three share the URL

    refined = LLMGroupRefiner(_Runs([[0], [1, 2]])).refine(groups)

    assert [[e.event for e in g.events] for g in refined] == [["clickTextField"], ["Paste", "changeField"]]


def test_refinement_prompt_numbers_events_and_explains_focus_and_effect_events() -> None:
    llm = _Runs([[0], [1, 2]])
    refiner = LLMGroupRefiner(llm, element_attributes=["element_id"])
    refiner.refine(EventGrouper().group_events_with_context_switches(_fill_form_events()))

    prompt = llm.prompts[0]
    assert "[0] clickTextField (target: lPupZ)" in prompt
    assert "[1] Paste" in prompt
    assert "only record the effect of an action" in prompt
    assert "is a UI activity of its own (focusing the field)" in prompt


def test_refinement_rejects_runs_that_skip_an_event() -> None:
    groups = EventGrouper().group_events_with_context_switches(_fill_form_events())

    with pytest.raises(ValueError, match="non-consecutive"):
        LLMGroupRefiner(_Runs([[0, 2], [1]])).refine(groups)


def test_refinement_rejects_runs_that_miss_an_event() -> None:
    groups = EventGrouper().group_events_with_context_switches(_fill_form_events())

    with pytest.raises(ValueError, match="incomplete"):
        LLMGroupRefiner(_Runs([[0], [1]])).refine(groups)


# ── implicit activities ─────────────────────────────────────────────────────

def _main(i, pattern, target=None, target_id=None, rows=None):
    return Activity(name=f"A{i}", confidence=0.9, pattern_name=pattern, group_index=i,
                    source_events=rows or [i], target=target, target_id=target_id)


def _sequence(groups, mains, apps=("app",)):
    return [(a.activity_type, a.pattern_name) for a in add_implicit_activities(groups, mains, list(apps))]


def test_find_then_focus_then_write_with_one_find() -> None:
    groups = [EventGroup(events=[Event("click", {"app": "Edge"}, 0)]),
              EventGroup(events=[Event("paste", {"app": "Edge"}, 1)])]
    mains = [_main(0, "Focus", "First Name field", "id=lPupZ"),
             _main(1, "Write Element", "First Name field", "id=lPupZ")]

    assert _sequence(groups, mains) == [
        ("prerequisite", "Find Element"),
        ("main", "Focus"),
        ("main", "Write Element"),
    ]


def test_write_without_a_recorded_focus_gets_find_and_focus() -> None:
    groups = [EventGroup(events=[Event("paste", {"app": "Edge"}, 0)])]
    mains = [_main(0, "Write Element", "Last Name field", "id=abc")]

    assert _sequence(groups, mains) == [
        ("prerequisite", "Find Element"),
        ("prerequisite", "Focus"),
        ("main", "Write Element"),
    ]


def test_switch_comes_first_and_page_level_actions_need_no_find() -> None:
    groups = [EventGroup(events=[Event("getCell", {"app": "Excel"}, 0)]),
              EventGroup(events=[Event("openUrl", {"app": "Edge"}, 1)])]
    mains = [_main(0, "Read Element", "cell A2", "cell=A2"), _main(1, "Open", None, None)]

    assert _sequence(groups, mains) == [
        ("prerequisite", "Find Element"),
        ("main", "Read Element"),
        ("context_switch", "Switch Context"),
        ("main", "Open"),
    ]


def test_missing_application_is_no_switch_and_a_url_change_is_no_switch() -> None:
    groups = [EventGroup(events=[Event("a", {"app": "Edge", "url": "u1"}, 0)]),
              EventGroup(events=[Event("b", {"url": "u2"}, 1)]),
              EventGroup(events=[Event("c", {"app": "Edge", "url": "u3"}, 2)])]
    mains = [_main(0, "Open"), _main(1, "Scroll"), _main(2, "Refresh")]

    assert [t for t, _ in _sequence(groups, mains)] == ["main", "main", "main"]


def test_switch_names_both_applications() -> None:
    groups = [EventGroup(events=[Event("a", {"app": "Excel"}, 0)]),
              EventGroup(events=[Event("b", {"app": "Edge"}, 1)])]
    activities = add_implicit_activities(groups, [_main(0, "Open"), _main(1, "Open")], ["app"])

    assert activities[1].name == "Switch context from Excel to Edge"


def test_inferrer_identifies_targets_from_element_columns() -> None:
    inferrer = ActivityInferrer(None, element_attributes=["element_id"])
    events = [Event("Paste", {}, 0), Event("changeField", {"element_id": "lPupZ"}, 1)]

    assert inferrer._target_identity(events, "First Name field") == "element_id=lPupZ"
    assert inferrer._target_identity([Event("Paste", {}, 0)], "First Name field") == "first name field"


# ── end to end on the published Fill Form snippet ──────────────────────────

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
                "switch_columns": ["Application"],
                "group_columns": ["Application", "Workbook", "URL"],
                "environment_columns": {"web": ["URL", "Element ID"], "desktop": ["Workbook", "Cell range"], "screen": []},
                "element_columns": ["Element ID", "Cell range"],
            })
        if "grouping UI events into UI activities" in prompt:
            m = int(re.search(r"holding (\d+) events", prompt).group(1))
            assert m == 4
            return json.dumps([[0], [1], [2, 3]])
        if "RPA (Robotic Process Automation) designer" in prompt:
            return json.dumps([
                {"activity_name": "Read cell A2", "pattern": "Read Element", "target": "cell A2",
                 "evidence": [], "confidence": 0.9, "reasoning": ""},
                {"activity_name": "Focus First Name field", "pattern": "Focus", "target": "First Name field",
                 "evidence": [], "confidence": 0.9, "reasoning": ""},
                {"activity_name": "Write value into First Name field", "pattern": "Write Element",
                 "target": "First Name field", "evidence": [], "confidence": 0.9, "reasoning": ""},
            ])
        raise AssertionError("unexpected prompt")


def test_fill_form_snippet_yields_find_focus_write(tmp_path) -> None:
    path = tmp_path / "fill.csv"
    path.write_text(_FILL_FORM, encoding="utf-8")

    result = DataPipeline(str(path), llm_client=_FillFormLLM()).run()
    rows = [(r.pattern.name if r.pattern else None, r.activity_object, r.method) for r in result.recommendations]

    assert rows == [
        ("Find Element", "UI element", "UIA Tree Parsing"),
        ("Read Element", "UI element", "UI Automation tree parsing"),
        ("Switch Context", "Context", "UI Automation manipulation"),
        ("Find Element", "HTML element", "DOM parsing"),
        ("Focus", "HTML element", "HTML DOM manipulation"),
        ("Write Element", "HTML element", "DOM manipulation"),
    ]


# ── loader, object types, coverage ──────────────────────────────────────────

class _Columns:
    def complete(self, prompt):
        if "selecting the activity-name attribute" in prompt:
            return "event"
        return json.dumps({"switch_columns": ["app"], "group_columns": ["app"],
                           "environment_columns": {"web": [], "desktop": ["app"], "screen": []},
                           "element_columns": ["element_id", "made_up"]})


def test_loader_keeps_only_real_element_columns(tmp_path) -> None:
    path = tmp_path / "log.csv"
    path.write_text("event,app,element_id\nclick,Edge,x\n", encoding="utf-8")
    loader = CSVLoader(_Columns())
    loader.load(str(path))

    assert loader.detected_element_columns == ["element_id"]


def test_object_type_follows_the_environment_but_switch_context_acts_on_a_context() -> None:
    write = _by_name("Write Element")

    assert object_type_for(write, "web") == "HTML element"
    assert object_type_for(write, "desktop") == "UI element"
    assert object_type_for(write, "screen") == "visual element"
    assert object_type_for(_by_name("Switch Context"), "desktop") == "Context"


def test_uncovered_action_is_reported_as_not_covered() -> None:
    assert "not covered by the pattern collection" in explain_missing_method(None, "web")


def test_naming_accepts_a_null_pattern() -> None:
    class _NoPattern:
        def complete(self, prompt):
            return json.dumps([{"activity_name": "Drag file to folder", "pattern": None, "target": None,
                                "evidence": [], "confidence": 0.5, "reasoning": ""}])

    activities = ActivityInferrer(_NoPattern()).infer_activities([[Event("drag", {"app": "Explorer"}, 0)]])

    assert [(a.name, a.pattern_name) for a in activities] == [("Drag file to folder", None)]


def test_attribute_role_prompt_uses_attribute_terminology_and_keys(tmp_path) -> None:
    class _Roles:
        def __init__(self):
            self.prompts = []

        def complete(self, prompt):
            self.prompts.append(prompt)
            if "selecting the activity-name attribute" in prompt:
                return "event"
            return json.dumps({"switch_attributes": ["app"], "group_attributes": ["app"],
                               "environment_attributes": {"web": [], "desktop": ["app"], "screen": []},
                               "element_attributes": ["element_id"]})

    path = tmp_path / "log.csv"
    path.write_text("event,app,element_id\nclick,Edge,x\n", encoding="utf-8")
    llm = _Roles()
    loader = CSVLoader(llm)
    loader.load(str(path))

    assert loader.detected_switch_columns == ["app"]
    assert loader.detected_element_columns == ["element_id"]
    assert loader.detected_environment_columns["desktop"] == ["app"]
    assert all("column name" not in p for p in llm.prompts)


def test_naming_prompt_shows_the_identified_context_and_element_attributes() -> None:
    inferrer = ActivityInferrer(None, application_attributes=["Application"],
                                context_attributes=["URL", "Workbook"], element_attributes=["Element ID"])
    group = EventGroup(events=[Event("Paste", {"Application": "Edge", "URL": "https://a.test",
                                               "Element ID": "lPupZ"}, 0)])
    prompt = inferrer._build_batch_prompt([(0, group, None)])

    assert "  URL: https://a.test" in prompt
    assert "  Element ID: lPupZ" in prompt


def test_naming_rejects_a_pattern_outside_the_collection() -> None:
    from src.llm.client import LLMError

    class _Invented:
        def complete(self, prompt):
            return json.dumps([{"activity_name": "Drag file to folder", "pattern": "Drag Element",
                                "target": None, "evidence": [], "confidence": 0.5, "reasoning": ""}])

    with pytest.raises(LLMError, match="not in the pattern collection"):
        ActivityInferrer(_Invented(), patterns=PATTERNS).infer_activities([[Event("drag", {"app": "Explorer"}, 0)]])


def test_boundary_evidence_carries_context_values_forward() -> None:
    groups = [EventGroup(events=[Event("getCell", {"app": "Excel", "wb": "c.xlsx"}, 0)]),
              EventGroup(events=[Event("paste", {"app": "Edge", "url": "u"}, 1)]),
              EventGroup(events=[Event("getCell", {"app": "Excel", "wb": "c.xlsx"}, 2)])]
    llm = _Runs([[0], [1], [2]])
    LLMGroupRefiner(llm, application_attributes=["app"], context_attributes=["wb", "url"]).refine(groups)

    assert "wb NOT RECORDED in GROUP 1; last recorded c.xlsx in GROUP 0, GROUP 2 has c.xlsx (same as that)" in llm.prompts[0]


def test_find_precedes_scroll_and_refresh_only_when_they_act_on_an_element() -> None:
    groups = [EventGroup(events=[Event("scroll", {"app": "Edge"}, 0)]),
              EventGroup(events=[Event("scroll", {"app": "Edge"}, 1)]),
              EventGroup(events=[Event("open", {"app": "Edge"}, 2)])]
    mains = [_main(0, "Scroll", None, None), _main(1, "Scroll", "Results list", "results list"), _main(2, "Open")]

    assert _sequence(groups, mains) == [
        ("main", "Scroll"),
        ("prerequisite", "Find Element"),
        ("main", "Scroll"),
        ("main", "Open"),
    ]


def test_implicit_activities_are_named_by_action_object_and_context() -> None:
    groups = [EventGroup(events=[Event("paste", {"app": "Edge"}, 0)])]
    main = _main(0, "Write Element", "First Name field", "id=lPupZ")
    main.context = "on rpachallenge.com in Edge"

    names = [a.name for a in add_implicit_activities(groups, [main], ["app"])]

    assert names[:2] == ["Find First Name field on rpachallenge.com in Edge",
                         "Focus First Name field on rpachallenge.com in Edge"]


def test_naming_prompt_asks_for_action_object_context_without_values_or_uniqueness() -> None:
    prompt = ActivityInferrer(None)._build_batch_prompt([(0, EventGroup(events=[Event("Paste", {}, 0)]), None)])

    assert "Action + object + context" in prompt
    assert "Do not include input values" in prompt
    assert '"context"' in prompt
    assert "UNIQUE" not in prompt


def test_naming_prompt_separates_a_recorded_focusing_click_from_the_focus_added_by_the_rule() -> None:
    prompt = ActivityInferrer(None)._build_batch_prompt(
        [(0, EventGroup(events=[Event("clickTextField", {}, 0)]), None)])

    assert "a click on a text field gives it input focus, so it is a Focus, not an Activate" in prompt
    assert "focusing a field before writing when no focusing event was recorded" in prompt
    assert "such as a click on a text field, is not one of them: describe it as a Focus" in prompt
    assert "added afterwards by fixed rules" in prompt


def test_naming_prompt_tells_the_model_that_delete_keys_are_a_delete_not_a_write() -> None:
    prompt = ActivityInferrer(None)._build_batch_prompt(
        [(0, EventGroup(events=[Event("pressBackspace", {}, 0)]), None)])

    assert "keys that delete text delete it, so it is Delete Element, not Write Element" in prompt
    assert "even when the change of the field is recorded afterwards" in prompt


def test_naming_prompt_asks_what_a_delete_deletes() -> None:
    prompt = ActivityInferrer(None)._build_batch_prompt(
        [(0, EventGroup(events=[Event("pressBackspace", {}, 0)]), None)])

    assert '"deletes"' in prompt
    assert "'content' if the action deletes data held by an element while the element stays" in prompt
    assert "'element' if it deletes the element itself" in prompt


class _Answers:
    def __init__(self, *results):
        self.results = list(results)

    def complete(self, prompt):
        return json.dumps(self.results)


def _delete_answer(**extra):
    return {"activity_name": "Delete text in First Name field on rpachallenge.com in Edge", "pattern": "Delete Element",
            "target": "First Name field", "context": "on rpachallenge.com in Edge", "evidence": [],
            "confidence": 0.9, "reasoning": "", **extra}


def _infer_delete(answer):
    inferrer = ActivityInferrer(_Answers(answer), patterns=PATTERNS)
    activities = inferrer.infer_activities([[Event("pressBackspace", {"app": "Edge"}, 0)]])
    return [a for a in activities if not a.is_implicit]


@pytest.mark.parametrize("said, recorded", [("content", "content"), (" Element ", "element")])
def test_a_delete_records_whether_it_deletes_the_element_or_data_in_it(said, recorded) -> None:
    (main,) = _infer_delete(_delete_answer(deletes=said))

    assert main.deletes == recorded


@pytest.mark.parametrize("extra", [{}, {"deletes": None}, {"deletes": "text"}, {"deletes": True}])
def test_a_delete_without_a_usable_answer_stops_the_analysis(extra) -> None:
    from src.llm.client import LLMError

    with pytest.raises(LLMError, match="deletes the 'element' itself or its 'content'"):
        _infer_delete(_delete_answer(**extra))


def test_the_answer_is_ignored_for_every_other_pattern() -> None:
    (main,) = _infer_delete({**_delete_answer(deletes="content"), "pattern": "Write Element"})

    assert main.deletes is None
