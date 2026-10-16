"""Execution environment from LLM-identified columns, and prioritised method lists.

* The LLM identifies which columns indicate each environment when the log is loaded
  (in the same call that identifies the application and grouping columns), because
  column names differ between loggers. The environment of a UI activity is then the
  highest-priority one (web > desktop > screen) with a recorded value in its columns.
* Applicability is cumulative, so a pattern yields a prioritised list of methods:
  content-level, then accessibility-level, then visual/input-level — at most three.
"""

import json
import re

import pytest

from src.matching import PATTERNS
from src.matching.pattern_matcher import determine_environment, get_context_from_events
from src.models.event import Event
from src.models.pattern import MAX_RECOMMENDED_METHODS, Pattern
from src.parser.csv_loader import CSVLoader
from src.pipeline.data_pipeline import DataPipeline


def _by_name(name: str) -> Pattern:
    return next(p for p in PATTERNS if p.name == name)


# ── prioritised method lists ────────────────────────────────────────────────

def test_write_element_lists_every_level_the_environment_can_use() -> None:
    write = _by_name("Write Element")

    assert write.get_methods_for_context("web") == [
        "DOM manipulation", "UI Automation manipulation", "Hardware simulation",
    ]
    assert write.get_methods_for_context("desktop") == [
        "UI Automation manipulation", "Hardware simulation",
    ]
    assert write.get_methods_for_context("screen") == ["Hardware simulation"]


def test_extraction_patterns_end_with_visual_recognition() -> None:
    assert _by_name("Read Element").get_methods_for_context("web") == [
        "HTML DOM parsing", "UI Automation tree parsing", "Visual recognition",
    ]


def test_missing_level_shortens_the_list() -> None:
    hover = _by_name("Hover")  # no UI Automation variant

    assert hover.get_methods_for_context("web") == ["HTML DOM manipulation", "Hardware simulation"]
    assert hover.get_methods_for_context("desktop") == ["Hardware simulation"]


def test_unsupported_environment_gives_an_empty_list() -> None:
    assert _by_name("Delete Element").get_methods_for_context("screen") == []
    assert _by_name("Switch Context").get_methods_for_context("web") == []
    assert _by_name("Write Element").get_methods_for_context("unknown") == []


def test_switch_context_lists_both_desktop_variants() -> None:
    assert _by_name("Switch Context").get_methods_for_context("desktop") == [
        "UI Automation manipulation", "Hardware simulation",
    ]


@pytest.mark.parametrize("pattern", PATTERNS, ids=lambda p: p.name)
@pytest.mark.parametrize("context", ("web", "desktop", "screen"))
def test_top_of_the_list_is_the_single_method(pattern: Pattern, context: str) -> None:
    methods = pattern.get_methods_for_context(context)

    assert len(methods) <= MAX_RECOMMENDED_METHODS
    assert len(set(methods)) == len(methods)
    assert pattern.get_method_for_context(context) == (methods[0] if methods else None)


def test_list_is_ordered_by_level_not_by_file_order() -> None:
    pattern = Pattern(
        name="Example",
        action="Do",
        object="Element",
        method="Hardware thing (Visual) / DOM thing (Web) / UIA thing (Desktop)",
        category="Control",
        contexts=["web", "desktop", "screen"],
    )

    assert pattern.get_methods_for_context("web") == ["DOM thing", "UIA thing", "Hardware thing"]


def test_a_variant_written_for_several_environments_ranks_at_its_poorest() -> None:
    pattern = Pattern(
        name="Example",
        action="Do",
        object="Element",
        method="Shared thing (Web/Desktop/Screen) / UIA thing (Desktop)",
        category="Control",
        contexts=["web", "desktop", "screen"],
    )

    # A method that also runs on a bare screen is visual/input-level, so it comes last.
    assert pattern.get_methods_for_context("web") == ["UIA thing", "Shared thing"]


# ── environment from the identified columns ─────────────────────────────────

_COLUMNS = {"web": ["Page Address", "Node Path"], "desktop": ["Process Name"], "screen": ["PosX"]}


def test_environment_uses_the_identified_columns_whatever_their_names() -> None:
    events = [Event("select", {"Process Name": "EXCEL.EXE", "PosX": "120"}, 0)]

    assert determine_environment(events, _COLUMNS) == ("desktop", {"Process Name": "EXCEL.EXE"})


def test_web_takes_priority_over_desktop_and_screen() -> None:
    events = [
        Event("click", {"Process Name": "chrome.exe"}, 0),
        Event("click", {"Process Name": "chrome.exe", "Node Path": "/html/body/button"}, 1),
    ]

    environment, deciding = determine_environment(events, _COLUMNS)

    assert environment == "web"
    assert deciding == {"Node Path": "/html/body/button"}


def test_values_that_were_not_recorded_are_no_evidence() -> None:
    events = [Event("move", {"Page Address": "None", "Process Name": "", "PosX": "40"}, 0)]

    assert get_context_from_events(events, _COLUMNS) == "screen"


def test_no_identified_columns_means_unknown_environment() -> None:
    events = [Event("click", {"url": "https://example.test", "app": "Chrome"}, 0)]

    # The LLM found no environment columns: names alone are not used to guess.
    assert determine_environment(events, {"web": [], "desktop": [], "screen": []}) == ("unknown", {})


# ── the loader asks for the environment columns ─────────────────────────────

class _ColumnLLM:
    def __init__(self, column_roles: dict):
        self.column_roles = column_roles
        self.prompts = []

    def complete(self, prompt):
        self.prompts.append(prompt)
        if "selecting the event/action column" in prompt:
            return "event"
        return json.dumps(self.column_roles)


def _write(tmp_path, text):
    path = tmp_path / "log.csv"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_loader_keeps_only_real_columns_and_one_environment_per_column(tmp_path) -> None:
    llm = _ColumnLLM({
        "switch_columns": ["Process Name"],
        "group_columns": ["Process Name", "Page Address"],
        "environment_columns": {
            "web": ["Page Address", "Invented"],
            "desktop": ["Process Name", "Page Address"],
            "screen": ["PosX"],
        },
    })
    loader = CSVLoader(llm)
    loader.load(_write(tmp_path, "event,Process Name,Page Address,PosX\nclick,chrome.exe,https://a.test,3\n"))

    assert loader.detected_environment_columns == {
        "web": ["Page Address"],
        "desktop": ["Process Name"],
        "screen": ["PosX"],
    }
    roles_prompt = next(p for p in llm.prompts if "environment_columns" in p)
    assert "Classify by what the column describes, not by its name" in roles_prompt


def test_loader_reports_no_environment_columns_when_the_llm_gives_none(tmp_path) -> None:
    loader = CSVLoader(_ColumnLLM({"switch_columns": [], "group_columns": []}))
    loader.load(_write(tmp_path, "event,url\nclick,https://a.test\n"))

    assert loader.detected_environment_columns == {"web": [], "desktop": [], "screen": []}


# ── end to end through the CLI pipeline ─────────────────────────────────────

class _PipelineLLM:
    def complete(self, prompt):
        if "selecting the event/action column" in prompt:
            return "event"
        if '"environment_columns"' in prompt:
            return json.dumps({
                "switch_columns": ["Process Name"],
                "group_columns": ["Process Name", "Page Address"],
                "environment_columns": {"web": ["Page Address"], "desktop": ["Process Name"], "screen": []},
            })
        if "grouping UI events into UI activities" in prompt:
            n = int(re.search(r"Below are (\d+) candidate", prompt).group(1))
            return json.dumps([[i] for i in range(n)])
        if "RPA (Robotic Process Automation) designer" in prompt:
            n = int(re.search(r"EXACTLY (\d+) object", prompt).group(1))
            return json.dumps([
                {
                    "activity_name": f"Write value {i}",
                    "pattern": "Write Element",
                    "context_switch": {"detected": False},
                    "prerequisite": {"needed": False},
                    "evidence": ["e"],
                    "confidence": 0.9,
                    "reasoning": "r",
                }
                for i in range(n)
            ])
        raise AssertionError("unexpected prompt")


def test_pipeline_recommends_a_prioritised_list_per_environment(tmp_path) -> None:
    csv_path = _write(
        tmp_path,
        "event,Process Name,Page Address\n"
        "setCell,EXCEL.EXE,\n"
        "typeText,chrome.exe,https://form.test\n",
    )

    result = DataPipeline(csv_path, llm_client=_PipelineLLM()).run()
    records = [r.to_dict() for r in result.recommendations if r.pattern and r.pattern.name == "Write Element"]

    assert [r["execution_environment"] for r in records] == ["desktop", "web"]
    assert records[0]["methods"] == ["UI Automation manipulation", "Hardware simulation"]
    assert records[1]["methods"] == [
        "DOM manipulation", "UI Automation manipulation", "Hardware simulation",
    ]
    assert [r["method"] for r in records] == ["UI Automation manipulation", "DOM manipulation"]
    assert records[1]["context_attributes_used"] == ["Page Address"]
