"""Application switches: rules propose, the LLM decides, the log's data is the evidence.

* The rule-based grouper treats a *missing* application value as "no information", never as
  a different application, and compares each recorded application with the last recorded one.
* The refinement and activity-naming prompts show the LLM the log's application-related
  attributes (changed / same / not recorded, carried forward over groups that recorded none).
* The code never overrides the LLM on application switches; it only checks adjacency.
"""

import json
import re
import uuid

import pytest

from src.inference.activity_inferrer import ActivityInferrer
from src.inference.event_grouper import EventGroup, EventGrouper, LLMGroupRefiner
from src.models.event import Event, recorded_value
from src.pipeline.data_pipeline import DataPipeline


def _groups(events, **grouper_kwargs):
    return EventGrouper(**grouper_kwargs).group_events_with_context_switches(events)


def _names(groups):
    return [[e.event for e in g.events] for g in groups]


# ── recorded values ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw", [None, "", "  ", "None", "none", "NULL", "nan"])
def test_values_that_mean_nothing_was_recorded(raw) -> None:
    assert recorded_value(raw) is None


def test_recorded_value_is_stripped_text() -> None:
    assert recorded_value("  Excel ") == "Excel"
    assert recorded_value(42) == "42"


# ── rule-based grouper ──────────────────────────────────────────────────────

def test_missing_application_does_not_split_events_that_share_a_url() -> None:
    groups = _groups([
        Event("select", {"app": "Excel", "url": "u1"}, 0),
        Event("paste", {"url": "u1"}, 1),
        Event("click", {"app": "Excel", "url": "u1"}, 2),
    ])

    assert _names(groups) == [["select", "paste", "click"]]
    assert not groups[0].is_context_switch


def test_event_with_no_attributes_is_its_own_group_but_not_a_switch() -> None:
    groups = _groups([
        Event("select", {"app": "Excel"}, 0),
        Event("paste", {}, 1),
        Event("click", {"app": "Excel"}, 2),
    ])

    assert _names(groups) == [["select"], ["paste"], ["click"]]
    assert not any(g.is_context_switch for g in groups)
    assert all(g.previous_app is None and g.current_app is None for g in groups)


def test_switch_is_found_against_the_last_recorded_application() -> None:
    groups = _groups([
        Event("select", {"app": "Excel"}, 0),
        Event("paste", {}, 1),
        Event("open", {"app": "Chrome"}, 2),
    ])

    assert _names(groups) == [["select"], ["paste"], ["open"]]
    assert groups[1].is_context_switch  # the group that closed when Chrome appeared
    assert groups[2].previous_app == "Excel"  # not None: the blank event is skipped
    assert groups[2].current_app == "Chrome"


def test_no_switch_before_two_different_applications_have_been_recorded() -> None:
    groups = _groups([
        Event("click", {"url": "u1"}, 0),
        Event("click", {"app": "Excel", "url": "u1"}, 1),
        Event("click", {"app": "Excel", "url": "u1"}, 2),
    ])

    assert _names(groups) == [["click", "click", "click"]]


def test_two_different_recorded_applications_still_split() -> None:
    groups = _groups([Event("click", {"app": "Chrome"}, 0), Event("click", {"app": "Excel"}, 1)])

    assert len(groups) == 2
    assert groups[1].previous_app == "Chrome"
    assert groups[1].current_app == "Excel"


def test_literal_none_is_not_an_application() -> None:
    groups = _groups([
        Event("select", {"app": "Excel", "url": "u1"}, 0),
        Event("paste", {"app": "None", "url": "u1"}, 1),
        Event("click", {"app": "Excel", "url": "u1"}, 2),
    ])

    assert _names(groups) == [["select", "paste", "click"]]


def test_literal_none_is_not_a_shared_value() -> None:
    groups = _groups([Event("a", {"url": "None"}, 0), Event("b", {"url": "None"}, 1)])

    assert len(groups) == 2


def test_application_column_can_be_any_detected_name() -> None:
    events = [Event("a", {"Process Name": "EXCEL.EXE"}, 0), Event("b", {"Process Name": "chrome.exe"}, 1)]

    # Default switch attributes do not know this column: the events split (nothing links
    # them) but the boundary is not recognised as an application change.
    default = _groups(events)
    assert len(default) == 2
    assert default[1].previous_app is None

    detected = _groups(events, context_switch_attributes=["Process Name"])
    assert len(detected) == 2
    assert detected[1].previous_app == "EXCEL.EXE"
    assert detected[1].current_app == "chrome.exe"


# ── refinement prompt ───────────────────────────────────────────────────────

def _prompt(events, **refiner_kwargs):
    return LLMGroupRefiner(None, **refiner_kwargs)._build_prompt(_groups(events))


def test_refinement_prompt_leaves_the_decision_to_the_llm() -> None:
    prompt = _prompt([Event("a", {"app": "Excel"}, 0), Event("b", {"app": "Chrome"}, 1)])

    assert "hard boundar" not in prompt
    assert "[APP SWITCH]" not in prompt
    assert "never merge across" not in prompt.lower()
    assert "is your decision" in prompt


def test_refinement_prompt_shows_a_changed_application() -> None:
    prompt = _prompt([Event("a", {"app": "Excel"}, 0), Event("b", {"app": "Chrome"}, 1)])

    assert ">> between GROUP 0 and GROUP 1: app CHANGED Excel -> Chrome" in prompt
    assert "GROUP 0 [app: Excel]" in prompt
    assert "GROUP 1 [app: Chrome]" in prompt


def test_refinement_prompt_shows_a_missing_application_as_no_evidence() -> None:
    prompt = _prompt([
        Event("select", {"app": "Excel"}, 0),
        Event("paste", {}, 1),
        Event("click", {"app": "Excel"}, 2),
    ])

    assert "app NOT RECORDED in GROUP 1 (no evidence either way)" in prompt
    assert "GROUP 1 [application: not recorded]" in prompt


def test_refinement_prompt_carries_the_last_recorded_application_across_a_blank_group() -> None:
    changed = _prompt([
        Event("select", {"app": "Excel"}, 0),
        Event("paste", {}, 1),
        Event("open", {"app": "Chrome"}, 2),
    ])
    same = _prompt([
        Event("select", {"app": "Excel"}, 0),
        Event("paste", {}, 1),
        Event("click", {"app": "Excel"}, 2),
    ])

    assert "last recorded Excel in GROUP 0, GROUP 2 has Chrome (CHANGED from that)" in changed
    assert "last recorded Excel in GROUP 0, GROUP 2 has Excel (same as that)" in same


def test_refinement_prompt_says_when_no_group_records_an_application() -> None:
    prompt = _prompt([Event("a", {"url": "u1"}, 0), Event("b", {"url": "u2"}, 1)])

    assert "application NOT RECORDED in either group" in prompt
    assert "url CHANGED u1 -> u2" in prompt


def test_refinement_prompt_uses_the_application_columns_the_llm_identified() -> None:
    events = [Event("a", {"Process Name": "EXCEL.EXE"}, 0), Event("b", {"Process Name": "chrome.exe"}, 1)]
    prompt = _prompt(events, application_attributes=["Process Name"])

    assert "Application-related attributes in this log: Process Name." in prompt
    assert "Process Name CHANGED EXCEL.EXE -> chrome.exe" in prompt


def test_refinement_prompt_shows_other_context_columns_and_clips_long_values() -> None:
    long_url = "https://example.test/" + "x" * 200
    prompt = _prompt(
        [Event("a", {"Page": "home"}, 0), Event("b", {"Page": long_url}, 1)],
        context_attributes=["Page"],
    )

    assert "Page CHANGED home -> https://example.test/" in prompt
    assert "x" * 100 not in prompt
    assert "..." in prompt


def test_refinement_prompt_marks_boundaries_only_inside_a_batch() -> None:
    groups = [EventGroup(events=[Event(f"e{i}", {"app": "Excel"}, i)]) for i in range(4)]

    prompt = LLMGroupRefiner(None)._build_prompt(groups)

    assert prompt.count(">> between GROUP") == 3


class _MergeEverything:
    def __init__(self):
        self.batch_sizes = []

    def complete(self, prompt):
        n = int(re.search(r"Below are (\d+) candidate", prompt).group(1))
        self.batch_sizes.append(n)
        return json.dumps([list(range(n))])


def test_the_llms_answer_is_final_the_code_only_checks_adjacency() -> None:
    groups = _groups([Event("select", {"app": "Excel"}, 0), Event("open", {"app": "Chrome"}, 1)])
    assert len(groups) == 2

    refined = LLMGroupRefiner(_MergeEverything()).refine(groups)

    assert _names(refined) == [["select", "open"]]


def test_refinement_still_works_in_batches_of_ten() -> None:
    groups = [EventGroup(events=[Event(f"e{i}", {"app": "Excel"}, i)]) for i in range(12)]
    llm = _MergeEverything()

    refined = LLMGroupRefiner(llm).refine(groups)

    assert llm.batch_sizes == [10, 2]
    assert len(refined) == 2


# ── activity-naming prompt ──────────────────────────────────────────────────

def _naming_prompt(groups, **inferrer_kwargs):
    inferrer = ActivityInferrer(None, **inferrer_kwargs)
    running, previous = {}, [None] * len(groups)
    for i, group in enumerate(groups):
        if i:
            previous[i] = dict(running)
        running.update(inferrer._latest_context(group.events))
    return inferrer._build_batch_prompt([(i, g, previous[i]) for i, g in enumerate(groups)])


def _previous_context(prompt, group_number):
    block = prompt.split(f"GROUP {group_number}:")[1]
    return re.search(r"Previous context: (.*)", block).group(1)


def test_previous_context_carries_the_application_across_a_group_that_recorded_none() -> None:
    prompt = _naming_prompt([
        EventGroup(events=[Event("select", {"app": "Excel", "url": "u1"}, 0)]),
        EventGroup(events=[Event("paste", {"url": "u1"}, 1)]),
        EventGroup(events=[Event("open", {"app": "Chrome"}, 2)]),
    ])

    assert "first activity" in _previous_context(prompt, 1)
    assert _previous_context(prompt, 2) == "app=Excel, url=u1"
    assert _previous_context(prompt, 3) == "app=Excel, url=u1"  # not just the blank group's url


def test_previous_context_says_when_earlier_groups_recorded_nothing() -> None:
    prompt = _naming_prompt([
        EventGroup(events=[Event("click", {}, 0)]),
        EventGroup(events=[Event("click", {"app": "Excel"}, 1)]),
    ])

    text = _previous_context(prompt, 2)
    assert "first activity" not in text
    assert "no application, URL or window was recorded in earlier groups" in text


def test_previous_context_uses_the_latest_recorded_value() -> None:
    prompt = _naming_prompt([
        EventGroup(events=[Event("a", {"app": "Excel"}, 0), Event("b", {"app": "Word"}, 1)]),
        EventGroup(events=[Event("c", {}, 2)]),
    ])

    assert _previous_context(prompt, 2) == "app=Word"


def test_naming_prompt_uses_the_application_columns_the_llm_identified() -> None:
    prompt = _naming_prompt(
        [
            EventGroup(events=[Event("select", {"Process Name": "EXCEL.EXE"}, 0)]),
            EventGroup(events=[Event("open", {"Process Name": "chrome.exe"}, 1)]),
        ],
        application_attributes=["Process Name"],
    )

    assert _previous_context(prompt, 2) == "Process Name=EXCEL.EXE"
    assert "Process Name: chrome.exe" in prompt
    assert "application-related attributes (Process Name)" in prompt


def test_naming_prompt_asks_for_log_evidence_and_ignores_a_missing_application() -> None:
    prompt = _naming_prompt([EventGroup(events=[Event("click", {"app": "Excel"}, 0)])])

    assert "NOT RECORDED in this group is no evidence either way" in prompt
    assert 'name the changed attribute values in "evidence"' in prompt


# ── the columns identified at load time reach both prompts ──────────────────

_CSV = "event,Process Name,Page\nselect,EXCEL.EXE,\npaste,,\nopen,chrome.exe,https://example.test\n"


class _RecordingLLM:
    """Answers each kind of prompt the pipeline sends and records them."""

    def __init__(self):
        self.prompts = []

    def complete(self, prompt):
        self.prompts.append(prompt)
        if "selecting the event/action column" in prompt:
            return "event"
        if '"switch_columns"' in prompt:
            return json.dumps({"switch_columns": ["Process Name"], "group_columns": ["Process Name", "Page"]})
        if "grouping UI events into discrete tasks" in prompt:
            n = int(re.search(r"Below are (\d+) candidate", prompt).group(1))
            return json.dumps([[i] for i in range(n)])
        if "RPA (Robotic Process Automation) designer" in prompt:
            n = int(re.search(r"EXACTLY (\d+) object", prompt).group(1))
            return json.dumps([
                {
                    "activity_name": f"Activity {i}",
                    "pattern": "Activate",
                    "context_switch": {"detected": False},
                    "prerequisite": {"needed": False},
                    "evidence": ["e"],
                    "confidence": 0.9,
                    "reasoning": "r",
                }
                for i in range(n)
            ])
        raise AssertionError("unexpected prompt")

    def prompt_containing(self, text):
        return next(p for p in self.prompts if text in p)


def test_cli_pipeline_gives_both_llm_prompts_the_detected_application_columns(tmp_path) -> None:
    csv_path = tmp_path / "log.csv"
    csv_path.write_text(_CSV, encoding="utf-8")
    llm = _RecordingLLM()

    pipeline = DataPipeline(str(csv_path), llm_client=llm)
    pipeline.run()

    assert pipeline.refiner.application_attributes == ["Process Name"]
    assert pipeline.refiner.context_attributes == ["Page"]
    assert pipeline.inferrer.application_attributes == ["Process Name"]
    refinement = llm.prompt_containing("grouping UI events into discrete tasks")
    assert "Application-related attributes in this log: Process Name." in refinement
    assert "last recorded EXCEL.EXE in GROUP 0, GROUP 2 has chrome.exe (CHANGED from that)" in refinement
    naming = llm.prompt_containing("RPA (Robotic Process Automation) designer")
    assert "Previous context: Process Name=EXCEL.EXE" in naming


def test_web_pipeline_stores_the_detected_columns_and_uses_them_for_naming(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("src.web.step_store._STORE_DIR", str(tmp_path / "progressive"))
    llm = _RecordingLLM()
    monkeypatch.setattr("src.llm.client.get_llm_client", lambda *a, **k: llm)
    monkeypatch.setattr("src.web.progressive._get_history", lambda: [{"id": "h", "progressive_artifacts": {}}])
    monkeypatch.setattr("src.web.progressive._save_history", lambda h: None)

    from src.web import progressive
    from src.web.step_store import StepStore

    csv_path = tmp_path / "log.csv"
    csv_path.write_text(_CSV, encoding="utf-8")
    aid = str(uuid.uuid4())
    store = StepStore(aid)
    store.save("meta", {"aid": aid, "history_id": "h", "filename": "log.csv",
                        "filepath": str(csv_path), "event_column": "event"})

    step1 = progressive._compute_step1(store)
    store.save_step(1, step1)

    assert step1["application_attributes"] == ["Process Name"]
    assert step1["context_attributes"] == ["Page"]
    refinement = llm.prompt_containing("grouping UI events into discrete tasks")
    assert "last recorded EXCEL.EXE in GROUP 0, GROUP 2 has chrome.exe (CHANGED from that)" in refinement

    progressive._step2_progress[aid] = {"status": "computing", "completed": 0, "total": 0}
    progressive._run_step2_thread(aid)

    assert progressive._step2_progress[aid]["status"] == "done"
    naming = llm.prompt_containing("RPA (Robotic Process Automation) designer")
    assert "Previous context: Process Name=EXCEL.EXE" in naming
