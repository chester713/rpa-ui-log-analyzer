"""The sequence graph: the rows of an export become the UI activities, one box each, in the order of the log.

Every row of the exported analysis is a log event, or an implicit activity inserted before the UI
activity it precedes. The graph keeps each activity once, with what its five layers colour it by: where
it came from (the log or a rule), its pattern, its context, its execution environment and its
recommended methods. A stored analysis and its exported CSV give the same graph; only the context
columns differ, because a file does not say which attributes the LLM identified.
"""

import csv
import io
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import app as webapp
from src.web.step_store import StepStore
from src.web.visualisation import (
    EXPORT_COLUMNS, _context_per_slot, _roles_from_names, _short, build_model, rows_from_export,
)

TEMPLATES = Path(__file__).resolve().parents[1] / "templates"
LOG_COLUMNS = ["category", "application", "concept:name", "workbook", "current_worksheet", "browser_url", "clipboard_content"]
NOT_COVERED = "No method: no pattern matched this activity, which is not covered by the pattern collection."


def _export(*rows) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["row", *LOG_COLUMNS, *EXPORT_COLUMNS])
    writer.writerows(rows)
    return out.getvalue()


def _activity(no, name, pattern, action, object_type, target, environment, selected, methods, note=""):
    return [no, "recorded", name, pattern, action, object_type, target, environment, selected, methods, note]


def _implicit(no, rule, name, pattern, action, object_type, target, environment, selected, methods):
    return ["", *[""] * len(LOG_COLUMNS), no, f"implicit ({rule})", name, pattern, action, object_type, target,
            environment, selected, methods, ""]


def _event(row, application, name, activity=None, workbook="", sheet="", url="", clipboard=""):
    return [row, "category", application, name, workbook, sheet, url, clipboard, *(activity or [""] * len(EXPORT_COLUMNS))]


FIND_CELL = "Find cell A2 in Sheet1 of challenge.xlsx in Excel"
READ = _activity(2, "Read cell A2 in Sheet1 of challenge.xlsx in Excel", "Read Element", "Read", "UI element", "cell A2",
                 "desktop", "UI Automation tree parsing", "UI Automation tree parsing > Visual recognition")
FIELD = _activity(5, "Activate text field on rpachallenge.com in Edge", "Activate", "Activate", "HTML element",
                  "text field", "web", "HTML DOM manipulation",
                  "HTML DOM manipulation > UI Automation manipulation > Hardware simulation")
WRITE = _activity(6, "Write text field on rpachallenge.com in Edge", "Write Element", "Write", "HTML element",
                  "text field", "web", "DOM manipulation", "DOM manipulation > UI Automation manipulation > Hardware simulation")
CLOSE = _activity(8, "Close workbook in Excel", "", "", "", "", "desktop", "", "", NOT_COVERED)

SAMPLE = _export(
    _implicit(1, "find", FIND_CELL, "Find Element", "Find", "UI element", "cell A2", "desktop", "UIA Tree Parsing",
              "UIA Tree Parsing > Visual Recognition"),
    _event(0, "Microsoft Excel", "getCell", READ, workbook="challenge.xlsx", sheet="Sheet1"),
    _implicit(3, "switch", "Switch context from Microsoft Excel to Edge", "Switch Context", "Switch", "Context", "",
              "desktop", "UI Automation manipulation", "UI Automation manipulation > Hardware simulation"),
    _implicit(4, "find", "Find text field on rpachallenge.com in Edge", "Find Element", "Find", "HTML element",
              "text field", "web", "DOM parsing", "DOM parsing > UIA Tree Parsing > Visual Recognition"),
    _event(1, "Edge", "clickTextField", FIELD, url="https://rpachallenge.com/"),
    _event(2, "Edge", "paste", WRITE, url="https://rpachallenge.com/", clipboard="John\n"),
    _event(3, "Edge", "changeField", WRITE, url="https://rpachallenge.com/"),
    _implicit(7, "switch", "Switch context from Edge to Microsoft Excel", "Switch Context", "Switch", "Context", "",
              "desktop", "UI Automation manipulation", "UI Automation manipulation > Hardware simulation"),
    _event(4, "Microsoft Excel", "closeWorkbook", CLOSE, workbook="challenge.xlsx", sheet="Sheet1"),
    _event(5, "Microsoft Excel", "afterCalculate"),  # an event that belongs to no activity
)


@pytest.fixture()
def model():
    return build_model(rows_from_export(SAMPLE), title="sample.csv")


@pytest.fixture()
def by_no(model):
    return {a["no"]: a for a in model["activities"]}


# ── reading an export ────────────────────────────────────────────────────────

def test_an_export_is_read_row_by_row_with_its_multi_line_values() -> None:
    source = rows_from_export(SAMPLE)

    assert source["columns"] == LOG_COLUMNS
    assert [r["row"] for r in source["rows"]] == [None, 0, None, None, 1, 2, 3, None, 4, 5]
    assert source["rows"][5]["values"]["clipboard_content"] == "John\n"
    implicit = [r for r in source["rows"] if r["row"] is None]
    assert all(r["values"] == {} and r["activity"]["type"] == "implicit" for r in implicit)
    assert [r["activity"]["rule"] for r in implicit] == ["find", "switch", "find", "switch"]
    assert source["rows"][-1]["activity"] is None


@pytest.mark.parametrize("text", ["event,application\nclick,Edge\n", "row,event\n0,click\n", "", "\n"])
def test_a_file_that_is_not_an_export_is_refused(text) -> None:
    with pytest.raises(ValueError, match="not an exported analysis"):
        rows_from_export(text)


def test_blank_rows_and_rows_without_event_or_activity_are_skipped() -> None:
    padded = SAMPLE + "\n" + ",".join([""] * (1 + len(LOG_COLUMNS) + len(EXPORT_COLUMNS))) + "\n"

    assert len(rows_from_export(padded)["rows"]) == len(rows_from_export(SAMPLE)["rows"])


def test_a_selected_method_without_a_list_is_the_only_method() -> None:
    text = _export(_event(0, "Edge", "click", _activity(1, "Activate OK", "Activate", "Activate", "HTML element", "OK",
                                                        "web", "Hardware simulation", "")))

    [row] = rows_from_export(text)["rows"]

    assert [m["name"] for m in row["activity"]["methods"]] == ["Hardware simulation"]
    assert row["activity"]["selected"] == "Hardware simulation"


# ── the activities ───────────────────────────────────────────────────────────

def test_the_activities_come_in_the_order_of_the_log_one_box_each(model) -> None:
    assert [a["no"] for a in model["activities"]] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert [a["origin"] for a in model["activities"]] == [
        "find", "recorded", "switch", "find", "recorded", "recorded", "switch", "recorded"]
    assert model["activities"][0]["name"] == FIND_CELL
    assert model["roles"] == {"event_column": "concept:name", "software": ["application"],
                              "data": ["browser_url", "workbook", "current_worksheet"], "from_names": True}
    assert (model["source"], model["aid"], model["title"]) == ("export", None, "sample.csv")


def test_identical_names_stay_separate_boxes() -> None:
    again = _activity(2, "Read cell A2 in Sheet1 of challenge.xlsx in Excel", "Read Element", "Read", "UI element",
                      "cell A2", "desktop", "UI Automation tree parsing", "UI Automation tree parsing")
    text = _export(_event(0, "Excel", "getCell", READ), _event(1, "Excel", "getCell", [3, *again[1:]]))

    assert [a["no"] for a in build_model(rows_from_export(text))["activities"]] == [2, 3]


def test_an_activity_knows_its_events_pattern_category_and_environment(by_no) -> None:
    read = by_no[2]
    assert (read["origin"], read["pattern"], read["category"], read["environment"]) == (
        "recorded", "Read Element", "Extraction", "desktop")
    assert [(e["row"], e["name"]) for e in read["events"]] == [(0, "getCell")]
    write = by_no[6]  # two events make one UI activity
    assert [(e["row"], e["name"]) for e in write["events"]] == [(2, "paste"), (3, "changeField")]
    assert (write["category"], write["object_type"], write["target"]) == ("Modification", "HTML element", "text field")
    switch = by_no[3]
    assert (switch["origin"], switch["category"], switch["events"]) == ("switch", "Control", [])


def test_an_event_keeps_the_values_it_recorded_whole_and_leaves_out_the_empty_ones(by_no) -> None:
    paste, change = by_no[6]["events"]

    assert paste["attrs"]["clipboard_content"] == "John\n"
    assert "workbook" not in paste["attrs"]
    assert change["attrs"]["browser_url"] == "https://rpachallenge.com/"


def test_an_activity_has_the_application_and_data_context_of_its_events(by_no) -> None:
    assert [(by_no[n]["software"], by_no[n]["data"]) for n in (1, 2, 3, 4, 5, 6, 7, 8)] == [
        ("Microsoft Excel", "challenge.xlsx · Sheet1"), ("Microsoft Excel", "challenge.xlsx · Sheet1"),
        ("Edge", "rpachallenge.com"), ("Edge", "rpachallenge.com"), ("Edge", "rpachallenge.com"),
        ("Edge", "rpachallenge.com"), ("Microsoft Excel", "challenge.xlsx · Sheet1"),
        ("Microsoft Excel", "challenge.xlsx · Sheet1")]


def test_the_applications_are_listed_in_the_order_they_appear(model) -> None:
    assert model["software_names"] == ["Microsoft Excel", "Edge"]


def test_a_switch_says_which_applications_it_switches_between(by_no) -> None:
    assert by_no[3]["switch"] == {"from": "Microsoft Excel", "to": "Edge"}
    assert by_no[7]["switch"] == {"from": "Edge", "to": "Microsoft Excel"}
    assert "switch" not in by_no[2]


def test_a_switch_named_in_other_words_takes_its_applications_from_the_events() -> None:
    text = _export(
        _event(0, "Excel", "getCell", READ),
        _implicit(3, "switch", "Go to the other window", "Switch Context", "Switch", "Context", "", "desktop",
                  "UI Automation manipulation", "UI Automation manipulation"),
        _event(1, "Edge", "paste", WRITE),
    )

    switch = build_model(rows_from_export(text))["activities"][1]

    assert switch["switch"] == {"from": "Excel", "to": "Edge"}


def test_an_activity_no_pattern_covers_has_no_methods_and_says_why(by_no) -> None:
    close = by_no[8]

    assert (close["pattern"], close["category"], close["methods"], close["selected"]) == (None, None, [], None)
    assert close["note"] == NOT_COVERED


def test_the_figures_count_each_kind_of_activity(model) -> None:
    assert model["stats"] == {
        "events": 6, "events_without_activity": 1, "activities": 4,
        "implicit": {"find": 2, "focus": 0, "switch": 2}, "not_covered": 1, "with_method": 7,
        "software_contexts": 2,
    }


# ── the methods ──────────────────────────────────────────────────────────────

def test_a_method_has_its_family_level_and_the_reason_it_applies(by_no) -> None:
    assert [(m["name"], m["family"], m["level"], m["level_name"]) for m in by_no[6]["methods"]] == [
        ("DOM manipulation", "DOM manipulation", 0, "content-level"),
        ("UI Automation manipulation", "UIA manipulation", 1, "accessibility-level"),
        ("Hardware simulation", "Hardware simulation", 2, "visual and input level"),
    ]
    assert [m["why"] for m in by_no[6]["methods"]] == [
        "A web environment has content-level methods of its own.",
        "Applicable by cumulation: a web object can also be acted on by accessibility-level methods.",
        "Applicable by cumulation: a web object can also be acted on by visual and input level methods.",
    ]
    assert by_no[2]["methods"][0]["why"] == "A desktop environment has accessibility-level methods of its own."


def test_the_wording_of_a_pattern_file_is_kept_next_to_its_family(by_no) -> None:
    assert [(m["name"], m["family"]) for m in by_no[1]["methods"]] == [
        ("UIA Tree Parsing", "UIA parsing"), ("Visual Recognition", "Visual recognition")]


def test_the_selected_method_is_found_by_name_and_is_the_first_when_none_is_named(by_no) -> None:
    assert [by_no[n]["selected"] for n in (1, 2, 6, 8)] == [0, 0, 0, None]
    chosen = _activity(1, "Open the file", "Open", "Open", "UI element", "", "desktop", "Hardware simulation",
                       "UI Automation manipulation > Hardware simulation")
    unnamed = _activity(2, "Open the file", "Open", "Open", "UI element", "", "desktop", "A method not in the list",
                        "UI Automation manipulation > Hardware simulation")
    text = _export(_event(0, "Excel", "open", chosen), _event(1, "Excel", "open", unnamed))

    first, second = build_model(rows_from_export(text))["activities"]

    assert (first["selected"], second["selected"]) == (1, 0)


def test_a_method_of_no_known_family_has_a_name_and_no_level() -> None:
    odd = _activity(1, "Open the file", "Open", "Open", "UI element", "", "desktop", "Telepathy", "Telepathy")

    [method] = build_model(rows_from_export(_export(_event(0, "Excel", "open", odd))))["activities"][0]["methods"]

    assert (method["name"], method["family"], method["level"], method["level_name"], method["why"]) == (
        "Telepathy", "Telepathy", None, None, None)


def test_the_reasons_agree_with_the_ones_each_pattern_gives() -> None:
    from src.matching import PATTERNS

    for pattern in PATTERNS:
        for environment in ("web", "desktop", "screen"):
            names = pattern.get_methods_for_context(environment)
            text = _export(_event(0, "Excel", "x", _activity(1, "A", pattern.name, "", "", "", environment,
                                                             names[0] if names else "", " > ".join(names))))
            [activity] = build_model(rows_from_export(text))["activities"]
            given = [v["why"] for v in pattern.describe_methods(environment) if v["applicable"]]

            assert [m["why"] for m in activity["methods"]] == given, (pattern.name, environment)


# ── the context columns ──────────────────────────────────────────────────────

def test_the_roles_are_taken_from_the_column_names() -> None:
    assert _roles_from_names(["Row", "Event", "Application", "URL", "Workbook"]) == {
        "event": "Event", "software": ["Application"], "data": ["URL", "Workbook"]}
    assert _roles_from_names(["id", "label"])["event"] == "id"  # no usual name: the first column
    assert _roles_from_names([]) == {"event": None, "software": [], "data": []}


def _event_row(row, **values):
    return {"row": row, "values": values, "activity": None}


def _implicit_row():
    return {"row": None, "values": {}, "activity": None}


def test_a_value_that_was_not_recorded_continues_the_context_but_a_new_application_starts_afresh() -> None:
    rows = [
        _event_row(0, app="Excel", doc="a.xlsx"),
        _event_row(1, app="Excel"),                                 # no document recorded: still a.xlsx
        _implicit_row(),                                            # inserted before the next event
        _event_row(2, app="Edge"),                                  # a new application: no document of Excel's
        _event_row(3, app="Edge", url="https://x.com/p?q=1"),
        _implicit_row(),                                            # after the last event
    ]

    software, data = _context_per_slot(rows, ["app"], ["url", "doc"])

    assert software == ["Excel", "Excel", "Edge", "Edge", "Edge", "Edge"]
    assert data == ["a.xlsx", "a.xlsx", None, None, "x.com/p", "x.com/p"]


@pytest.mark.parametrize("value, shown", [
    ("https://rpachallenge.com/", "rpachallenge.com"),
    ("https://ntp.msn.com/edge/ntp?locale=en-US&title=New%20tab", "ntp.msn.com/edge/ntp"),
    ("edge://newtab/", "edge://newtab"),
    ("Book1", "Book1"),
])
def test_a_context_value_is_shown_short(value, shown) -> None:
    assert _short(value) == shown


def test_a_long_context_value_is_cut() -> None:
    assert len(_short("x" * 60)) == 40 and _short("x" * 60).endswith("…")


# ── the routes ───────────────────────────────────────────────────────────────

def _post(data):
    return webapp.app.test_client().post("/visualisation/open-export", data=data, content_type="multipart/form-data")


def test_the_page_without_an_analysis_asks_for_an_export() -> None:
    html = webapp.app.test_client().get("/visualisation").get_data(as_text=True)

    assert "Open an exported analysis" in html and "window.__MODEL__ = null;" in html


def test_the_server_turns_an_export_into_a_model() -> None:
    response = _post({"file": (io.BytesIO(SAMPLE.encode("utf-8")), "sample export.csv")})

    assert response.status_code == 200
    data = response.get_json()
    assert len(data["activities"]) == 8 and data["title"] == "sample_export.csv"


def test_a_file_saved_with_a_byte_order_mark_is_read() -> None:
    response = _post({"file": (io.BytesIO(b"\xef\xbb\xbf" + SAMPLE.encode("utf-8")), "x.csv")})

    assert response.status_code == 200 and len(response.get_json()["activities"]) == 8


@pytest.mark.parametrize("data, message", [
    ({}, "No file selected"),
    ({"file": (io.BytesIO(b"event,application\nclick,Edge\n"), "log.csv")}, "not an exported analysis"),
    ({"file": (io.BytesIO("row,café\n".encode("cp1252")), "x.csv")}, "UTF-8"),
])
def test_a_file_that_cannot_be_drawn_is_explained(data, message) -> None:
    response = _post(data)

    assert response.status_code == 400
    assert message in response.get_json()["error"]


def test_an_unknown_analysis_is_not_found(monkeypatch) -> None:
    monkeypatch.setattr(webapp, "get_history", lambda: [])

    assert webapp.app.test_client().get("/visualisation/missing").status_code == 404


def test_an_analysis_that_is_not_normalised_yet_points_to_step_3(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("src.web.step_store._STORE_DIR", str(tmp_path / "progressive"))
    store = StepStore("a1")
    store.save("meta", {"aid": "a1", "history_id": "h1", "filename": "f.csv", "filepath": str(tmp_path / "none.csv")})
    store.save_step(1, {"segments": [{"segment_index": 0, "rows": [0], "labels": ["click"], "boundary": None}],
                        "groups": [{"group_index": 0, "events": [{"event": "click", "row_index": 0, "attributes": {}}]}]})
    monkeypatch.setattr(webapp, "get_history", lambda: [{"id": "h1", "filename": "f.csv", "progressive_aid": "a1"}])

    html = webapp.app.test_client().get("/visualisation/h1").get_data(as_text=True)

    assert "have not been normalised yet" in html and "window.__MODEL__ = null;" in html


# ── the page ─────────────────────────────────────────────────────────────────

def _page() -> str:
    return (TEMPLATES / "visualisation.html").read_text(encoding="utf-8")


def test_the_page_puts_log_text_on_the_graph_as_text_only() -> None:
    template = _page()

    assert "innerHTML" not in template and "insertAdjacentHTML" not in template
    assert "{% raw %}" in template  # the script is not a template
    assert "infer" not in template.lower()


def test_the_page_has_the_five_layers_and_the_downloads() -> None:
    template = _page()

    for label in ("Origin", "Pattern", "Context", "Environment", "Method"):
        assert f"label: '{label}'" in template
    assert 'id="svgBtn"' in template and 'id="pngBtn"' in template


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_script_of_the_page_is_valid_javascript(tmp_path) -> None:
    script = re.search(r"\{% raw %\}(.*?)\{% endraw %\}", _page(), re.S).group(1)
    path = tmp_path / "page.js"
    path.write_text(script, encoding="utf-8")

    result = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr


def test_the_other_pages_link_to_the_graph() -> None:
    for name in ("results.html", "workspace.html", "history.html"):
        assert "/visualisation/{{ entry.id }}" in (TEMPLATES / name).read_text(encoding="utf-8"), name
