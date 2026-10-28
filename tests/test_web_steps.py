"""The web app shows the seven steps of the approach, from the stored output of each step.

The run uses the RPA Challenge Fill Form pattern (read a cell in Excel, then focus a
field and paste into it in Edge) repeated 30 times, so the log has 120 events, and a
scripted LLM that answers prompts P1-P4 the way the approach prescribes.
"""

import csv
import io
import json
import re
import time

import pytest

import app as webapp
from src.web import progressive
from src.web.step_store import StepStore
from src.web.visualisation import build_model, rows_from_export

FIELDS = ["lPupZ", "mQ8xY"]


def _fill_form_csv(iterations=30):
    lines = ["Event,Application,Workbook,Worksheet,Cell range,Element ID,URL"]
    for i in range(iterations):
        field = FIELDS[i % 2]
        lines += [
            f"Get Cell,Microsoft Excel,challenge.xlsx,Sheet 1,A{i + 2},,",
            f"clickTextField,Edge,,,,{field},https://rpachallenge.com/",
            "Paste,Edge,,,,,https://rpachallenge.com/",
            f"changeField,Edge,,,,{field},https://rpachallenge.com/",
        ]
    return "\n".join(lines) + "\n"


class _ScriptedLLM:
    """Answers P1-P4 for the Fill Form log."""

    def complete(self, prompt):
        if "selecting the activity-name attribute" in prompt:
            return "Event"
        if '"environment_attributes"' in prompt:
            return json.dumps({
                "switch_attributes": ["Application"],
                "group_attributes": ["Application", "Workbook", "Worksheet", "URL"],
                "environment_attributes": {"web": ["URL", "Element ID"],
                                           "desktop": ["Application", "Workbook", "Worksheet", "Cell range"],
                                           "screen": []},
                "element_attributes": ["Element ID", "Cell range"],
            })
        if "grouping UI events into UI activities" in prompt:
            events = re.findall(r"^\s+\[(\d+)\] (\S+)", prompt, re.M)
            runs = []
            for number, name in events:
                if name == "changeField":
                    runs[-1].append(int(number))  # the effect of the paste
                else:
                    runs.append([int(number)])
            return json.dumps(runs)
        if "RPA (Robotic Process Automation) designer" in prompt:
            results = []
            for block in prompt.split("\nGROUP ")[1:]:
                first = re.search(r"Events:\n- ([^(\n]+)", block).group(1).strip()
                if first == "Get Cell":
                    cell = re.search(r"Cell range: (\S+)", block).group(1)
                    results.append({"activity_name": f"Read cell {cell} in Sheet 1 of challenge.xlsx in Excel",
                                    "pattern": "Read Element", "target": f"cell {cell}",
                                    "context": "in Sheet 1 of challenge.xlsx in Excel"})
                elif first == "clickTextField":
                    results.append({"activity_name": "Focus First Name field on rpachallenge.com in Edge",
                                    "pattern": "Focus", "target": "First Name field",
                                    "context": "on rpachallenge.com in Edge"})
                else:
                    results.append({"activity_name": "Write First Name field on rpachallenge.com in Edge",
                                    "pattern": "Write Element", "target": "First Name field",
                                    "context": "on rpachallenge.com in Edge"})
            for r in results:
                r.update({"evidence": ["scripted"], "confidence": 0.9, "reasoning": "scripted"})
            return json.dumps(results)
        raise AssertionError("unexpected prompt: " + prompt[:80])


@pytest.fixture()
def analysis(monkeypatch, tmp_path):
    """Upload the log, run steps 1-2 and step 3, and return (client, history id, aid)."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "uploads").mkdir(parents=True)
    monkeypatch.setattr("src.web.step_store._STORE_DIR", str(tmp_path / "data" / "progressive"))
    monkeypatch.setattr("src.llm.client.get_llm_client", lambda *a, **k: _ScriptedLLM())
    upload = tmp_path / "data" / "uploads" / "x_fill.csv"
    upload.write_text(_fill_form_csv(), encoding="utf-8")

    client = webapp.app.test_client()
    with client.session_transaction() as s:
        s["uploaded_file"] = str(upload)
        s["filename"] = "fill.csv"
    response = client.get("/p/start-progressive?event_column=Event&llm_column=Event")
    assert response.status_code == 302, response.headers.get("Location")
    history_id = re.search(r"/workspace/([^#]+)#segment", response.headers["Location"]).group(1)
    aid = webapp.get_history()[0]["progressive_aid"]

    assert client.post(f"/p/{aid}/normalise/start").get_json()["status"] in ("started", "done")
    for _ in range(100):
        if client.get(f"/p/{aid}/normalise/poll").get_json()["status"] == "done":
            break
        time.sleep(0.05)
    else:
        raise AssertionError(progressive._step2_progress.get(aid))
    return client, history_id, aid


def _view(html):
    return json.loads(re.search(r"const VIEW = (\{.*?\});\n", html, re.S).group(1))


def test_workspace_shows_the_seven_steps_in_order(analysis) -> None:
    client, history_id, _ = analysis
    html = client.get(f"/workspace/{history_id}").get_data(as_text=True)

    keys = re.findall(r'<section class="stage-card" data-stage="(\w+)"', html)
    assert keys == ["segment", "abstract", "normalise", "implicit", "match", "environment", "methods"]
    titles = re.findall(r'<h2 class="stage-title">(Step \d: [^<]+)</h2>', html)
    assert titles[0] == "Step 1: Segment events by context"
    assert titles[6] == "Step 7: Recommend prioritised methods"
    assert "Stage 1: UI activity identification" in html and "Stage 2: Method recommendation" in html
    assert "infer" not in html.lower()


def test_step_1_segments_are_stored_with_the_reason_for_each_boundary(analysis) -> None:
    client, history_id, _ = analysis
    view = _view(client.get(f"/workspace/{history_id}").get_data(as_text=True))

    first = view["segments"][:3]
    assert [s["rows"] for s in first] == [[0], [1, 2, 3], [4]]
    assert first[1]["boundary"] == "application changed: Microsoft Excel → Edge"
    assert view["roles"]["event_column_source"] == "proposed by the LLM, confirmed by the analyst"
    # Step 2 divides the Edge segment: the focusing click is a UI activity of its own.
    assert [u["rows"] for u in view["ui_activities"][:3]] == [[0], [1], [2, 3]]


def test_implicit_activities_follow_switch_find_focus_and_switch_is_desktop(analysis) -> None:
    client, history_id, _ = analysis
    view = _view(client.get(f"/results/{history_id}").get_data(as_text=True))
    seq = [(a["kind"], a["rule"], a["pattern"]) for a in view["activities"][:6]]

    assert seq == [
        ("implicit", "find", "Find Element"),
        ("recorded", None, "Read Element"),
        ("implicit", "switch", "Switch Context"),
        ("implicit", "find", "Find Element"),
        ("recorded", None, "Focus"),
        ("recorded", None, "Write Element"),
    ]
    switch = view["activities"][2]
    assert switch["environment"] == "desktop"
    assert switch["object_type"] == "Context"
    assert switch["name"] == "Switch context from Microsoft Excel to Edge"
    find = view["activities"][3]
    assert find["name"] == "Find First Name field on rpachallenge.com in Edge"
    assert find["environment"] == "web" and find["object_type"] == "HTML element"
    write = view["activities"][5]
    assert write["methods"] == ["DOM manipulation", "UI Automation manipulation", "Hardware simulation"]
    assert write["confidence"] == 0.9 and find["confidence"] is None


def test_results_cover_the_entire_log_and_the_graph_is_one_path(analysis) -> None:
    client, history_id, _ = analysis
    html = client.get(f"/results/{history_id}").get_data(as_text=True)
    view = _view(html)

    assert len(view["log"]["rows"]) == 120
    assert html.count('<tr data-row-index="') == 120
    names = [a["name"] for a in view["activities"]]
    assert len(set(names)) < len(names)  # the same UI activity recurs in every iteration
    nodes, edges = view["graph"]["nodes"], view["graph"]["edges"]
    assert len(nodes) == len(names)
    assert edges == [{"source": i, "target": i + 1} for i in range(len(nodes) - 1)]
    assert 'id="exportBtn"' in html


def test_results_before_normalisation_point_to_step_3(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("src.web.step_store._STORE_DIR", str(tmp_path / "progressive"))
    store = StepStore("a1")
    store.save("meta", {"aid": "a1", "history_id": "h1", "filename": "f.csv", "filepath": str(tmp_path / "none.csv")})
    store.save_step(1, {"segments": [{"segment_index": 0, "rows": [0], "labels": ["click"], "boundary": None}],
                        "groups": [{"group_index": 0, "events": [{"event": "click", "row_index": 0, "attributes": {}}]}]})
    monkeypatch.setattr(webapp, "get_history", lambda: [{"id": "h1", "filename": "f.csv", "progressive_aid": "a1"}])

    html = webapp.app.test_client().get("/results/h1").get_data(as_text=True)

    assert "#normalise" in html


def test_workspace_states_what_the_llm_decided_in_each_of_its_steps(analysis) -> None:
    client, history_id, _ = analysis
    html = client.get(f"/workspace/{history_id}").get_data(as_text=True)
    view = _view(html)

    # Steps 1 (P1, P2): the role the LLM gave every attribute of the log.
    attributes = {a["name"]: a for a in view["roles"]["attributes"]}
    assert list(attributes) == ["Event", "Application", "Workbook", "Worksheet", "Cell range", "Element ID", "URL"]
    assert attributes["Event"]["roles"] == ["Activity name (P1)"]
    assert attributes["Element ID"]["roles"] == ["Target element", "Web indicator"]
    assert attributes["Cell range"]["roles"] == ["Target element", "Desktop indicator"]
    assert attributes["Application"]["examples"] == ["Microsoft Excel", "Edge"]

    # Step 2 (P3): what the LLM did with each segment. Every Excel segment is kept; every Edge
    # segment is divided, because the click that focuses the field is a UI activity of its own.
    assert [u["decision"]["note"] for u in view["ui_activities"][:3]] == [
        "Kept segment S1 as one UI activity",
        "Divided segment S2: part 1 of 2",
        "Divided segment S2: part 2 of 2",
    ]
    assert view["abstraction"] == {"segments": 60, "ui_activities": 90, "kept": 30, "divided": 30, "combined": 0}

    # Step 3 (P4): the pattern chosen for every UI activity, with the LLM's own reasoning and evidence.
    assert view["normalisation"] == {"activities": 90, "matched": 90, "not_covered": 0}
    write = next(a for a in view["activities"] if a["pattern"] == "Write Element")
    assert (write["reasoning"], write["evidence"]) == ("scripted", ["scripted"])
    assert "Decisions made by the LLM: attribute roles" in html
    assert "The LLM\\'s decision for the selected UI activity" in html


def test_workspace_states_what_the_rules_and_the_lookup_decided_and_why(analysis) -> None:
    client, history_id, _ = analysis
    html = client.get(f"/workspace/{history_id}").get_data(as_text=True)
    view = _view(html)

    # Step 1: every segment starts because the application changed (the Excel/Edge alternation).
    assert view["segmentation"] == {"events": 120, "segments": 60, "application_changes": 59, "context_changes": 0,
                                    "context_attributes": [], "no_application": 0}
    assert view["segments"][1]["boundary_kind"] == "application"

    # Step 4: what each rule decided for each UI activity. The first iteration reads a cell (Find),
    # switches to Edge (Switch, Find), focuses the field and writes into it (no Find: the preceding
    # activity targets the same element; no Focus: the preceding activity focuses it).
    recorded = [a for a in view["activities"] if a["kind"] == "recorded"]
    read, focus, write = recorded[:3]
    assert [(c["rule"], c["inserted"]) for c in read["rule_checks"]] == [
        ("switch", False), ("find", True), ("focus", False)]
    assert [(c["rule"], c["inserted"]) for c in focus["rule_checks"]] == [
        ("switch", True), ("find", True), ("focus", False)]
    assert [(c["rule"], c["inserted"]) for c in write["rule_checks"]] == [
        ("switch", False), ("find", False), ("focus", False)]
    assert write["rule_checks"][1]["reason"].endswith("already targets it, so it is not located again.")
    assert view["implicit_rules"] == {"checked": 90, "switch": 59, "find": 60, "focus": 0}

    # Step 5: where each pattern comes from.
    assert (read["match_source"], focus["match_source"]) == ("llm", "llm")
    assert view["matching"] == {"activities": 209, "by_llm": 90, "by_rule": 119, "not_covered": 0}

    # Step 6: what the events record for each environment, and the one that decided.
    assert focus["environment"] == "web"
    assert focus["environment_evidence"]["web"]["recorded"] == {"URL": "https://rpachallenge.com/", "Element ID": "lPupZ"}
    assert focus["environment_evidence"]["desktop"]["recorded"] == {"Application": "Edge"}
    assert focus["environment_evidence"]["screen"] == {"checked": [], "recorded": {}}
    assert read["environment"] == "desktop" and read["environment_evidence"]["web"]["recorded"] == {}
    assert view["environments"] == {"web": 90, "desktop": 119, "screen": 0, "unknown": 0}

    # Step 7: every variant of the pattern and whether it applies.
    assert [(v["rank"]) for v in write["method_variants"]] == [1, 2, 3]
    assert [v["rank"] for v in read["method_variants"]] == [None, 1, 2]  # desktop: no content-level method
    assert view["recommendation"] == {"activities": 209, "with_method": 209, "not_covered": 0,
                                      "unknown_environment": 0, "no_variant": 0}
    assert "Decisions made by the rules: implicit activities" in html
    assert "Decisions made by lookup: matched patterns" in html


def _export_csv(view) -> str:
    """The analysis as Export CSV on the results page writes it: the implicit activities go
    immediately before the first event of the UI activity they precede."""
    columns = view["log"]["columns"]

    def info(a):
        return [a["number"], "recorded" if a["kind"] == "recorded" else f"implicit ({a['rule']})", a["name"],
                a["pattern"] or "", a["action"] or "", a["object_type"] or "", a["target"] or "", a["environment"],
                a["method"] or "", " > ".join(a["methods"]), a["method_note"] or ""]

    recorded_of_row = {r: a for a in view["activities"] if a["kind"] == "recorded" for r in a["rows"]}
    before, pending = {}, []
    for a in view["activities"]:
        if a["kind"] == "implicit":
            pending.append(a)
            continue
        if pending and a["rows"]:
            before[a["rows"][0]] = pending
        pending = []
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["row", *columns, "activity_no", "activity_type", "ui_activity", "pattern", "action",
                     "object_type", "target", "execution_environment", "selected_method", "prioritised_methods",
                     "method_note"])
    for row in view["log"]["rows"]:
        for imp in before.get(row["row_index"], []):
            writer.writerow(["", *[""] * len(columns), *info(imp)])
        a = recorded_of_row.get(row["row_index"])
        writer.writerow([row["row_index"], *[row["values"].get(c, "") for c in columns], *(info(a) if a else [""] * 11)])
    for imp in pending:
        writer.writerow(["", *[""] * len(columns), *info(imp)])
    return out.getvalue()


def test_the_graph_of_a_stored_analysis_equals_the_graph_of_its_export(analysis) -> None:
    client, history_id, aid = analysis
    page = client.get(f"/visualisation/{history_id}").get_data(as_text=True)
    stored = json.loads(re.search(r"window\.__MODEL__ = (\{.*?\});</script>", page, re.S).group(1))
    view = _view(client.get(f"/results/{history_id}").get_data(as_text=True))
    exported = build_model(rows_from_export(_export_csv(view)), title="export.csv")

    # What the graph shows of the Fill Form log: 120 events, 90 UI activities and the 119 implicit activities between them.
    assert stored["stats"] == {"events": 120, "events_without_activity": 0, "activities": 90,
                               "implicit": {"find": 60, "focus": 0, "switch": 59}, "not_covered": 0,
                               "with_method": 209, "software_contexts": 2}
    assert len(stored["activities"]) == 209
    assert (stored["source"], stored["aid"], stored["roles"]["software"]) == ("analysis", aid, ["Application"])

    # The same boxes in the same order, with the same events, contexts and methods, from the file alone;
    # only the context columns differ.
    def shape(model):
        return [(a["no"], a["origin"], a["name"], [(e["row"], e["name"]) for e in a["events"]], a["environment"],
                 a["pattern"], a["selected"], [(m["name"], m["why"]) for m in a["methods"]], a["software"], a["data"],
                 a.get("switch")) for a in model["activities"]]

    assert shape(stored) == shape(exported)
    assert stored["software_names"] == exported["software_names"]
    assert (stored["roles"]["from_names"], exported["roles"]["from_names"]) == (False, True)

    # What the LLM said is known only for a stored analysis.
    recorded = next(a for a in stored["activities"] if a["origin"] == "recorded")
    assert recorded["confidence"] == 0.9 and recorded["reasoning"] and recorded["index"] is not None
    assert "confidence" not in next(a for a in exported["activities"] if a["origin"] == "recorded")

