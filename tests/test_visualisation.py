"""The layered map: the rows of an export become layers aligned on one sequence.

Every row of the exported analysis is one slot: a log event, or an implicit activity inserted before
the UI activity it precedes. The layers are the context, the context switches, the implicit
activities, the UI activities, the log events, the execution environment and the recommended
methods. A stored analysis and its exported CSV give the same map; only the context columns differ,
because a file does not say which attributes the LLM identified.
"""

import csv
import io
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


# ── the layers ───────────────────────────────────────────────────────────────

def test_every_row_is_a_slot(model) -> None:
    assert [s["kind"] for s in model["slots"]] == [
        "implicit", "event", "implicit", "implicit", "event", "event", "event", "implicit", "event", "event"]
    assert [s["name"] for s in model["slots"]][1:7] == [
        "getCell", "Switch context from Microsoft Excel to Edge", "Find text field on rpachallenge.com in Edge",
        "clickTextField", "paste", "changeField"]
    assert model["slots"][0]["name"] == FIND_CELL
    assert model["roles"] == {"event_column": "concept:name", "software": ["application"],
                              "data": ["browser_url", "workbook", "current_worksheet"], "from_names": True}
    assert (model["source"], model["aid"], model["title"]) == ("export", None, "sample.csv")


def test_the_context_has_bands_and_every_switch_sits_where_the_application_changes(model) -> None:
    assert [(b["name"], b["from"], b["to"]) for b in model["bands"]["software"]] == [
        ("Microsoft Excel", 0, 1), ("Edge", 2, 6), ("Microsoft Excel", 7, 9)]
    assert [(b["name"], b["software"], b["from"], b["to"]) for b in model["bands"]["data"]] == [
        ("challenge.xlsx · Sheet1", "Microsoft Excel", 0, 1), ("rpachallenge.com", "Edge", 2, 6),
        ("challenge.xlsx · Sheet1", "Microsoft Excel", 7, 9)]
    assert [(s["slot"], s["from"], s["to"]) for s in model["switches"]] == [
        (2, "Microsoft Excel", "Edge"), (7, "Edge", "Microsoft Excel")]
    assert model["software_names"] == ["Microsoft Excel", "Edge"]


def test_an_activity_knows_its_slots_events_category_and_methods(model) -> None:
    by_no = {a["no"]: a for a in model["activities"]}

    assert sorted(by_no) == [1, 2, 3, 4, 5, 6, 7, 8]
    read = by_no[2]
    assert (read["type"], read["from"], read["to"], read["events"]) == ("recorded", 1, 1, [1])
    assert (read["category"], read["environment"], read["covered"]) == ("Extraction", "desktop", True)
    assert read["selected"] == "UI Automation tree parsing"
    assert [(m["name"], m["level"]) for m in read["methods"]] == [("UI Automation tree parsing", 1), ("Visual recognition", 2)]
    write = by_no[6]  # two events make one UI activity
    assert (write["from"], write["to"], write["events"], write["category"]) == (5, 6, [5, 6], "Modification")
    assert [m["level"] for m in write["methods"]] == [0, 1, 2]
    switch = by_no[3]
    assert (switch["type"], switch["rule"], switch["category"], switch["events"]) == ("implicit", "switch", "Control", [])


def test_an_activity_no_pattern_covers_has_no_methods_and_says_why(model) -> None:
    close = {a["no"]: a for a in model["activities"]}[8]

    assert (close["covered"], close["pattern"], close["category"], close["methods"], close["selected"]) == (
        False, None, None, [], None)
    assert close["note"] == NOT_COVERED


def test_an_event_without_an_activity_stays_on_the_map(model) -> None:
    orphan = model["slots"][9]

    assert (orphan["name"], orphan["activity"], orphan["environment"]) == ("afterCalculate", None, "unknown")
    assert orphan["software"] == "Microsoft Excel"


def test_a_slot_keeps_the_values_it_recorded_whole_and_leaves_out_the_empty_ones(model) -> None:
    assert model["slots"][5]["attrs"]["clipboard_content"] == "John\n"
    assert "workbook" not in model["slots"][4]["attrs"]
    assert model["slots"][4]["attrs"]["browser_url"] == "https://rpachallenge.com/"


def test_the_figures_count_each_kind_of_step(model) -> None:
    assert model["stats"] == {"events": 6, "activities": 4, "implicit": {"find": 2, "focus": 0, "switch": 2},
                              "not_covered": 1, "software_contexts": 2}


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
    assert len(data["slots"]) == 10 and data["title"] == "sample_export.csv"


def test_a_file_saved_with_a_byte_order_mark_is_read() -> None:
    response = _post({"file": (io.BytesIO(b"\xef\xbb\xbf" + SAMPLE.encode("utf-8")), "x.csv")})

    assert response.status_code == 200 and len(response.get_json()["slots"]) == 10


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

def test_the_page_puts_log_text_on_the_map_as_text_only() -> None:
    template = (TEMPLATES / "visualisation.html").read_text(encoding="utf-8")

    assert "innerHTML" not in template and "insertAdjacentHTML" not in template
    assert "{% raw %}" in template  # the script is not a template
    assert "infer" not in template.lower()


def test_the_other_pages_link_to_the_map() -> None:
    for name in ("results.html", "workspace.html", "history.html"):
        assert "/visualisation/{{ entry.id }}" in (TEMPLATES / name).read_text(encoding="utf-8"), name
