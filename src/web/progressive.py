"""Progressive pipeline of the web app: the seven steps of the approach, stage by stage.

The workspace shows the steps of the approach in their order (Section 4 of the paper):

  Stage 1 — UI activity identification
    1  Segment events by context          rules (attribute roles identified by the LLM at load: P1, P2)
    2  Abstract higher-level UI activities LLM in place of the SME (prompt P3)
    3  Normalise UI activities            LLM in place of the SME (prompt P4)
    4  Add implicit activities            rules
  Stage 2 — Method recommendation
    5  Match patterns                     lookup (P4 returned the pattern with the action)
    6  Determine environment, object type rules
    7  Recommend prioritised methods      rules

Steps 1 and 2 run when the analysis starts. Step 3 is the second LLM call and runs when
the analyst opens it; steps 4 to 7 are computed right after it. Every step's output is
stored (data/progressive/<aid>/) and the pages are built from these files, so the
workspace and the results page always show the same analysis.
"""

import csv as _csv
import json
import logging
import os
import shutil
import tempfile
import threading
import uuid
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import quote as _urlquote

from flask import Blueprint, jsonify, redirect, request, session

from .step_store import StepStore

_logger = logging.getLogger(__name__)

bp = Blueprint("progressive", __name__, url_prefix="/p")

# ── Stages: the steps of the approach ─────────────────────────────────────────

STAGES = [
    {"key": "segment", "step": 1, "stage": 1, "title": "Segment events by context"},
    {"key": "abstract", "step": 2, "stage": 1, "title": "Abstract higher-level UI activities"},
    {"key": "normalise", "step": 3, "stage": 1, "title": "Normalise UI activities"},
    {"key": "implicit", "step": 4, "stage": 1, "title": "Add implicit activities"},
    {"key": "match", "step": 5, "stage": 2, "title": "Match patterns"},
    {"key": "environment", "step": 6, "stage": 2, "title": "Determine environment and object type"},
    {"key": "methods", "step": 7, "stage": 2, "title": "Recommend prioritised methods"},
]
STAGE_KEYS = tuple(s["key"] for s in STAGES)
STAGE_GROUPS = {1: "UI activity identification", 2: "Method recommendation"}

# What each step does and why, shown under the step. (title, explanation) pairs.
STAGE_LOGIC: Dict[str, List[List[str]]] = {
    "segment": [
        ["Attribute roles", "Loggers name attributes differently, so when the log is loaded an LLM (prompt P2) "
         "identifies the role of each attribute by what it describes, not by its name: the application "
         "(software context), the further context such as webpage, window or worksheet (data context), "
         "the target element, and the attributes indicating each execution environment. The activity-name "
         "attribute is proposed by the LLM (prompt P1) and confirmed or changed by the analyst before the analysis starts."],
        ["Software context first", "Traversing the log in temporal order, consecutive events stay in the same "
         "interaction segment as long as they share their software context; a change of the recorded "
         "application starts a new segment."],
        ["Then data context", "Within one application, a change of a data-context value — a different webpage, "
         "worksheet or UI element — starts a new segment."],
        ["Missing values", "A value that was not recorded is no evidence of a change: an event is compared on the "
         "attributes it records, against the last value recorded in the segment (or, for the application, "
         "the last application recorded in the log)."],
        ["Evidence, not result", "Segments and UI activities need not coincide. The segments are the evidence "
         "from which step 2 starts, not a constraint on its result."],
    ],
    "abstract": [
        ["Collective intent", "In place of the SME, an LLM (prompt P3) receives the events of the segments, "
         "numbered and with their target elements, and decides which consecutive events form one UI activity: "
         "one action on one target."],
        ["What belongs together", "Repetitions of the same action on the same target, and events that only record "
         "the effect of an action (such as the change of a field registered when it loses focus), belong to "
         "that action. Any other event forms a UI activity of its own; clicking a text field before pasting "
         "into it is a separate UI activity."],
        ["Divide and combine", "A segment may be divided, and events of adjacent segments may be combined. "
         "Between adjacent segments the LLM is told, per attribute, whether the value is the same, changed or "
         "not recorded. A changed application counts strongly against combining, and when the evidence does "
         "not show one intent the events are kept apart."],
        ["Checked, not overridden", "The code does not change the LLM's answer; it only checks that every UI "
         "activity is a run of consecutive events and that every event belongs to exactly one UI activity. "
         "Segments are sent in batches of up to 10, so events on either side of a batch boundary are not combined."],
    ],
    "normalise": [
        ["Pattern vocabulary", "In place of the SME, an LLM (prompt P4) normalises each UI activity to the "
         "terminology of the pattern collection, choosing by the meaning of the interaction rather than the "
         "words of the log: a click on a button activates it, a click on a text field focuses it."],
        ["Action from the pattern", "The LLM returns the pattern of the UI activity. No two patterns share an "
         "action, so the pattern determines the normalised action; normalisation and pattern matching (step 5) "
         "are one judgement here."],
        ["Name: action + object + context", "Each UI activity is named by its action, its target object and the "
         "context the object resides in, e.g. 'Write First Name field on rpachallenge.com in Edge'. Input "
         "values are not part of the name."],
        ["Not covered", "If no pattern fits, the LLM returns none and the UI activity is reported as not covered "
         "by the pattern collection, rather than assigned to the closest pattern. A pattern name outside the "
         "collection stops the analysis."],
    ],
    "implicit": [
        ["Rules, in this order", "Some UI activities a bot must perform are not recorded. Three rules are applied, "
         "in this order, to each UI activity, each considering the activities already inserted."],
        ["Switch context", "When a UI activity is recorded in a different application from the last application "
         "recorded before it, a Switch Context activity is inserted. A missing application value is no evidence; "
         "a different webpage in the same application is not a switch. Switches between windows or tabs of one "
         "application are found only when the log records them."],
        ["Find", "Every UI activity that acts on a target element requires the bot to locate it first: Read, "
         "Observe, Write, Delete, Disable, Activate, Hover and Focus, and Scroll and Refresh when they act on an "
         "element rather than a whole page. A Find is inserted unless the preceding activity targets the same "
         "element. Open, Switch Context and Find itself need no Find."],
        ["Focus", "Writing requires the element to be focused for input. If the preceding activity does not focus "
         "it, a Focus activity is inserted. An element is therefore found, then focused, then written to."],
        ["Same element", "Two activities target the same element when they record the same element-attribute "
         "value (any of their events); if the log records no element attribute, the target object and context "
         "named by the LLM are compared."],
    ],
    "match": [
        ["One pattern per action", "Every UI activity matches the pattern whose action is its normalised action; "
         "implicit activities match the pattern they were inserted for. No model call is made in this step."],
        ["Environment checked later", "Whether the pattern can be carried out in the activity's execution "
         "environment is decided in step 7, so an activity keeps its pattern even when the pattern has no "
         "variant for its environment."],
    ],
    "environment": [
        ["Richest environment", "The execution environment of a UI activity is the richest one indicated by the "
         "attributes recorded for any of its events: web (HTML element or browser location), then desktop "
         "(native application interface or document structure), then screen (screen coordinates). A browser "
         "event also records desktop and screen attributes, so the richest one recorded is the richest interface "
         "representation available to a bot."],
        ["Object type", "The environment determines the object type: an HTML element (web), a UI element (desktop) "
         "or a visual element (screen). It is a property of the object; a poorer method chosen later does not "
         "change it. Switch Context acts on a context."],
        ["Implicit activities", "Find and Focus take the environment of the UI activity they precede. Switch Context "
         "always takes the desktop environment: switching between applications, windows or browser tabs is an "
         "operation of the desktop."],
        ["Unknown", "If no attribute indicating an environment is recorded for any event of the UI activity, the "
         "environment is reported as unknown and no method is recommended."],
    ],
    "methods": [
        ["Cumulative applicability", "An object in a richer environment can also be acted on by the methods of every "
         "poorer level: an HTML element is part of the DOM, exposed in the UI Automation tree and rendered on screen."],
        ["Prioritised list", "The applicable variants of the matched pattern are listed in order of level: "
         "content-level (DOM) first, then accessibility-level (UI Automation), then visual recognition and "
         "hardware simulation. A pattern defines at most one variant per level, so the list has at most three methods."],
        ["No method", "If the pattern defines no variant for the environment (e.g. Delete Element on screen), or the "
         "environment is unknown, or the UI activity is not covered by the collection, no method is recommended "
         "and the reason is stated."],
        ["Designer's choice", "The first method is the recommendation. On the results page the analyst can select "
         "another method from the list for each activity; the export uses the selected method."],
    ],
}

_SENSITIVE_FIELD_TOKENS = ("password", "passwd", "secret", "token", "api_key", "apikey", "authorization")

# ── Async state for the LLM step (step 3) ─────────────────────────────────────
_step2_lock = threading.Lock()
_step2_progress: dict = {}

# ── History helpers ───────────────────────────────────────────────────────────
_history_lock = threading.Lock()


def _get_history():
    path = "data/history.json"
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                return loaded if isinstance(loaded, list) else []
        except (json.JSONDecodeError, OSError):
            return []
    return []


def _save_history(history):
    path = "data/history.json"
    dir_path = os.path.dirname(os.path.abspath(path))
    os.makedirs(dir_path, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=dir_path,
                                     delete=False, suffix=".tmp") as f:
        json.dump(history, f, indent=2)
        tmp_path = f.name
    os.replace(tmp_path, path)


def _update_history_entry(history_id, **fields):
    with _history_lock:
        history = _get_history()
        for entry in history:
            if entry.get("id") == history_id:
                entry.update(fields)
                break
        _save_history(history)


# ── The recorded log ──────────────────────────────────────────────────────────

def _redact(row: dict) -> dict:
    return {
        k: ("[REDACTED]" if any(t in str(k or "").lower() for t in _SENSITIVE_FIELD_TOKENS) else v)
        for k, v in (row or {}).items()
    }


def load_log(filepath: str):
    """All rows of the uploaded log as (columns, [{row_index, values}]), sensitive fields redacted."""
    from src.parser.csv_loader import CSVLoader
    if not filepath or not os.path.exists(filepath):
        return [], []
    with open(filepath, "r", encoding="utf-8-sig", newline="") as f:
        reader = _csv.reader(f)
        headers = CSVLoader._dedup_headers(next(reader, []))
        rows = [
            {"row_index": i, "values": _redact({h: (vals[j] if j < len(vals) else "") for j, h in enumerate(headers)})}
            for i, vals in enumerate(reader)
        ]
    return headers, rows


# ── Serialisation helpers ─────────────────────────────────────────────────────

def _serialize_events(events):
    return [{"event": e.event, "row_index": e.row_index, "attributes": e.attributes} for e in events]


def _reconstruct_events(serialized):
    from src.models.event import Event
    return [Event(e["event"], e.get("attributes", {}), e.get("row_index")) for e in serialized]


def _reconstruct_groups(step1):
    from src.inference.event_grouper import EventGroup
    return [
        EventGroup(
            events=_reconstruct_events(g["events"]),
            is_context_switch=g.get("is_context_switch", False),
            previous_app=g.get("previous_app"),
            current_app=g.get("current_app"),
        )
        for g in step1["groups"]
    ]


def _serialize_activity(a):
    return {
        "name": a.name,
        "confidence": a.confidence,
        "evidence": list(a.evidence or []),
        "reasoning": a.reasoning or "",
        "source_events": list(a.source_events or []),
        "activity_type": a.activity_type,
        "is_implicit": a.is_implicit,
        "group_index": a.group_index,
        "pattern_name": a.pattern_name,
        "target": a.target,
        "target_id": a.target_id,
        "context": getattr(a, "context", None),
    }


# ── Step computations ─────────────────────────────────────────────────────────

def _compute_step1(store):
    """Attribute roles, step 1 (segments, rules) and step 2 (UI activities, LLM)."""
    from src.parser.csv_loader import CSVLoader
    from src.inference.event_grouper import EventGrouper, LLMGroupRefiner
    from src.llm.client import get_llm_client

    meta = store.load("meta")
    # The model was chosen when the event column was selected at upload (that first task
    # may have switched to the backup model). Stay on it for every later step; only if
    # none was recorded does this client start on the main model.
    llm_client = get_llm_client(model=meta.get("llm_model"))
    loader = CSVLoader(llm_client)
    if meta.get("event_column"):
        loader._force_column = meta["event_column"]

    events = loader.load(meta["filepath"])

    grouper = EventGrouper()
    if loader.detected_group_columns:
        grouper.group_attributes = loader.detected_group_columns
    if loader.detected_switch_columns:
        grouper.context_switch_attributes = loader.detected_switch_columns
    element_attributes = list(loader.detected_element_columns or [])
    grouper.element_attributes = element_attributes

    # Step 1: segmentation by software and data context (rules).
    segments = grouper.group_events_with_context_switches(events)

    # Step 2: the LLM abstracts UI activities from the segments. It is shown the same
    # application, context and element attributes the segmentation used.
    application_attributes = list(grouper.context_switch_attributes)
    context_attributes = [c for c in grouper.group_attributes if c not in application_attributes]
    refiner = LLMGroupRefiner(
        llm_client,
        application_attributes=application_attributes,
        context_attributes=context_attributes,
        element_attributes=element_attributes,
    )
    groups = refiner.refine(segments)

    return {
        "segments": [
            {"segment_index": i, "rows": [e.row_index for e in s.events], "labels": [e.event for e in s.events],
             "boundary": s.boundary}
            for i, s in enumerate(segments)
        ],
        "groups": [
            {"group_index": i, "events": _serialize_events(g.events), "is_context_switch": g.is_context_switch,
             "previous_app": g.previous_app, "current_app": g.current_app}
            for i, g in enumerate(groups)
        ],
        "group_count": len(groups),
        "event_count": len(events),
        "event_column": loader.detected_column,
        "application_attributes": application_attributes,
        "context_attributes": context_attributes,
        "environment_columns": loader.detected_environment_columns,
        "element_columns": element_attributes,
        # The model this analysis runs on (every later step stays on it).
        "llm_model": getattr(llm_client, "model", None),
        "llm_backup_used": bool(getattr(llm_client, "used_backup", False)),
    }


def compute_recommendations(step1: dict, step2: dict) -> List[dict]:
    """Steps 5 to 7 for every activity of the sequence (recorded and implicit)."""
    from src.matching import PATTERNS
    from src.matching.pattern_matcher import determine_environment
    from src.models.pattern import explain_missing_method, object_type_for

    patterns_by_name = {p.name.lower(): p for p in PATTERNS}
    groups = step1["groups"]
    environment_columns = step1.get("environment_columns")
    by_group = {}
    for g in groups:
        by_group[g["group_index"]] = determine_environment(_reconstruct_events(g["events"]), environment_columns)

    records = []
    for a in step2["activities"]:
        pattern = patterns_by_name.get((a.get("pattern_name") or "").strip().lower())
        is_switch = a.get("activity_type") == "context_switch"
        if is_switch:
            environment, deciding = "desktop", {}
            environment_note = ("Switch Context always takes the desktop environment: switching between "
                                "applications, windows or browser tabs is an operation of the desktop.")
        else:
            environment, deciding = by_group.get(a.get("group_index"), ("unknown", {}))
            environment_note = None
            if a.get("is_implicit"):
                environment_note = "Takes the environment of the UI activity it precedes."
        methods = pattern.get_methods_for_context(environment) if pattern else []
        records.append({
            "pattern": pattern.name if pattern else None,
            "action": pattern.action if pattern else None,
            "category": pattern.category if pattern else None,
            "pattern_description": pattern.description if pattern else None,
            "object_type": object_type_for(pattern, environment),
            "environment": environment,
            "deciding": deciding,
            "environment_note": environment_note,
            "methods": methods,
            "method": methods[0] if methods else None,
            "method_note": explain_missing_method(pattern, environment),
        })
    return records


def _run_step2_thread(aid):
    """Step 3 (LLM, prompt P4) and step 4 (rules), then steps 5 to 7 (rules)."""
    store = StepStore(aid)
    try:
        from src.inference.activity_inferrer import ActivityInferrer
        from src.matching import PATTERNS
        from src.llm.client import get_llm_client

        step1 = store.load_step(1)
        groups = _reconstruct_groups(step1)

        with _step2_lock:
            _step2_progress[aid].update({"total": len(groups)})

        def _on_progress(completed, total):
            with _step2_lock:
                _step2_progress[aid].update({"completed": completed, "total": total})

        # Same model as every earlier step of this analysis; never switch mid-analysis.
        meta = store.load("meta")
        llm_client = get_llm_client(model=meta.get("llm_model"), allow_failover=False)
        inferrer = ActivityInferrer(
            llm_client,
            progress_callback=_on_progress,
            patterns=PATTERNS,
            application_attributes=step1.get("application_attributes"),
            context_attributes=step1.get("context_attributes"),
            element_attributes=step1.get("element_columns"),
        )
        activities = inferrer.infer_activities(groups)
        if not activities:
            raise RuntimeError("Normalisation produced no UI activities — the LLM may be unavailable.")

        step2 = {"activities": [_serialize_activity(a) for a in activities]}
        store.save_step(3, {"recommendations": compute_recommendations(step1, step2)})
        # Written last: the poller treats step 2 as "done".
        store.save_step(2, step2)

        meta = store.load("meta")
        _update_history_entry(meta["history_id"], activity_count=len(activities))

        with _step2_lock:
            _step2_progress[aid]["status"] = "done"
    except Exception as exc:  # surfaced to the analyst; there is no fallback
        _logger.exception("Normalisation (step 3) failed")
        with _step2_lock:
            _step2_progress[aid] = {"status": "error", "error": str(exc)}


# ── The view shown by the workspace and results pages ─────────────────────────

_RULE_OF_PATTERN = {"Switch Context": "switch", "Find Element": "find", "Focus": "focus"}

_EXAMPLE_VALUES = 3
_EXAMPLE_CHARS = 40


def _attribute_roles(columns, rows, step1, event_column) -> List[dict]:
    """Prompts P1 and P2: the role the LLM gave each attribute of the log, with example values.

    An attribute can hold several roles (an element id is a target element and a web
    indicator) or none. The examples are the first distinct values recorded for it.
    """
    roles: Dict[str, List[str]] = {}

    def give(attributes, role):
        for attribute in attributes or []:
            if attribute:
                roles.setdefault(attribute, []).append(role)

    give([event_column], "Activity name (P1)")
    give(step1.get("application_attributes"), "Application (software context)")
    give(step1.get("context_attributes"), "Data context")
    give(step1.get("element_columns"), "Target element")
    environment = step1.get("environment_columns") or {}
    for name in ("web", "desktop", "screen"):
        give(environment.get(name), f"{name.capitalize()} indicator")

    table = []
    for column in columns or list(roles):
        examples: List[str] = []
        for row in rows:
            value = str(row["values"].get(column, "")).strip()
            if value and value not in examples:
                examples.append(value)
                if len(examples) == _EXAMPLE_VALUES:
                    break
        table.append({
            "name": column,
            "roles": roles.get(column, []),
            "examples": [v if len(v) <= _EXAMPLE_CHARS else v[:_EXAMPLE_CHARS - 1] + "…" for v in examples],
        })
    return table


def _abstraction_decisions(segments, ui_activities):
    """Prompt P3: what the LLM did with the rule-based segments of step 1.

    A UI activity keeps a segment as it is, is one part of a segment the LLM divided, or
    combines events of adjacent segments across a boundary the rules had drawn. P3 returns
    no reasons, so only the outcome is stated (and, where the LLM combined, the boundary the
    rules had drawn there). Returns one decision per UI activity, and the counts.
    """
    boundary = {s["segment_index"]: s.get("boundary") for s in segments}
    parts: Dict[int, List[int]] = {s["segment_index"]: [] for s in segments}
    for u in ui_activities:
        for s in u["segments"]:
            parts[s].append(u["index"])

    def names(indexes):
        labels = [f"S{i + 1}" for i in indexes]
        return labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " and " + labels[-1]

    counts = {"segments": len(segments), "ui_activities": len(ui_activities),
              "kept": 0, "divided": 0, "combined": 0}
    decisions = []
    for u in ui_activities:
        touched = u["segments"]
        if not touched:
            decisions.append(None)
        elif len(touched) > 1:
            crossed = [boundary[s] for s in touched[1:] if boundary.get(s)]
            note = f"Combined events of {names(touched)}"
            if crossed:
                note += f"; the rules had split them ({'; '.join(crossed)})"
            decisions.append({"kind": "combined", "note": note})
            counts["combined"] += len(touched) - 1
        else:
            siblings = parts[touched[0]]
            if len(siblings) == 1:
                decisions.append({"kind": "kept", "note": f"Kept segment {names(touched)} as one UI activity"})
            else:
                decisions.append({
                    "kind": "divided",
                    "note": f"Divided segment {names(touched)}: part {siblings.index(u['index']) + 1} of {len(siblings)}",
                })

    by_index = {u["index"]: u for u in ui_activities}
    for segment, siblings in parts.items():
        if len(siblings) > 1:
            counts["divided"] += 1
        elif siblings and by_index[siblings[0]]["segments"] == [segment]:
            counts["kept"] += 1
    return decisions, counts


def build_view(store) -> dict:
    """Everything the workspace and the results page show, built from the stored steps."""
    meta = store.load("meta") or {}
    step1 = store.load_step(1)
    step2 = store.load_step(2)
    step3 = store.load_step(3)
    columns, rows = load_log(meta.get("filepath"))

    view = {
        "aid": store.aid,
        "filename": meta.get("filename"),
        "log": {"columns": columns, "rows": rows},
        "roles": {},
        "segments": [],
        "ui_activities": [],
        "abstraction": None,
        "normalisation": None,
        "activities": [],
        "graph": {"nodes": [], "edges": []},
        "available": {key: False for key in STAGE_KEYS},
        "outdated": False,
    }
    if not step1 or "segments" not in step1:
        view["outdated"] = bool(step1)
        return view

    event_column = meta.get("event_column") or step1.get("event_column")
    proposed = meta.get("llm_column") or None  # what the LLM proposed at upload (prompt P1)
    if proposed and proposed == event_column:
        event_column_source = "proposed by the LLM, confirmed by the analyst"
    elif proposed:
        event_column_source = f"selected by the analyst; the LLM had proposed {proposed}"
    else:
        event_column_source = "selected by the analyst; the LLM did not propose an attribute of the log"
    view["roles"] = {
        "event_column": event_column,
        "event_column_source": event_column_source,
        "application": step1.get("application_attributes") or [],
        "context": step1.get("context_attributes") or [],
        "element": step1.get("element_columns") or [],
        "environment": step1.get("environment_columns") or {},
        "attributes": _attribute_roles(columns, rows, step1, event_column),
    }
    view["segments"] = step1["segments"]

    row_to_segment = {}
    for s in step1["segments"]:
        for r in s["rows"]:
            row_to_segment[r] = s["segment_index"]
    for g in step1["groups"]:
        rows_ = [e["row_index"] for e in g["events"]]
        view["ui_activities"].append({
            "index": g["group_index"],
            "rows": rows_,
            "labels": [e["event"] for e in g["events"]],
            "segments": sorted({row_to_segment[r] for r in rows_ if r in row_to_segment}),
        })
    decisions, view["abstraction"] = _abstraction_decisions(step1["segments"], view["ui_activities"])
    for ui_activity, decision in zip(view["ui_activities"], decisions):
        ui_activity["decision"] = decision
    view["available"]["segment"] = view["available"]["abstract"] = True

    if not step2 or not step3:
        return view

    recs = step3["recommendations"]
    for i, (a, rec) in enumerate(zip(step2["activities"], recs)):
        implicit = bool(a.get("is_implicit"))
        view["activities"].append({
            "index": i,
            "number": i + 1,
            "kind": "implicit" if implicit else "recorded",
            "rule": _RULE_OF_PATTERN.get(a.get("pattern_name")) if implicit else None,
            "name": a["name"],
            "target": a.get("target"),
            "context": a.get("context"),
            "ui_activity": a.get("group_index"),
            "rows": a.get("source_events") or [],
            "confidence": None if implicit else a.get("confidence"),
            "evidence": [] if implicit else (a.get("evidence") or []),
            "reasoning": a.get("reasoning") or "",
            **rec,
        })
    recorded = [a for a in view["activities"] if a["kind"] == "recorded"]
    view["normalisation"] = {
        "activities": len(recorded),
        "matched": sum(1 for a in recorded if a["pattern"]),
        "not_covered": sum(1 for a in recorded if not a["pattern"]),
    }
    view["graph"] = {
        "nodes": [{"id": a["index"], "label": a["name"], "kind": a["kind"], "rule": a["rule"]}
                  for a in view["activities"]],
        "edges": [{"source": i, "target": i + 1} for i in range(len(view["activities"]) - 1)],
    }
    for key in ("normalise", "implicit", "match", "environment", "methods"):
        view["available"][key] = True
    return view


# ── Routes ────────────────────────────────────────────────────────────────────

@bp.route("/start-progressive")
def start_progressive():
    """Run attribute roles and steps 1–2 for the uploaded log, then open the workspace."""
    filepath = session.get("uploaded_file")
    filename = session.get("filename")
    if not filepath or not os.path.exists(filepath):
        return redirect("/upload")

    event_column = request.args.get("event_column")
    llm_column = request.args.get("llm_column")
    aid = str(uuid.uuid4())
    history_id = str(uuid.uuid4())

    os.makedirs(os.path.join("data", "uploads"), exist_ok=True)
    prog_filepath = os.path.join("data", "uploads", f"{aid}_{filename}")
    shutil.copy2(filepath, prog_filepath)

    store = StepStore(aid)
    meta = {
        "aid": aid,
        "history_id": history_id,
        "filename": filename,
        "filepath": prog_filepath,
        "event_column": event_column,
        "llm_column": llm_column,
        # The model that answered the first task at upload (it may be the backup model).
        # Every later step of this analysis stays on it.
        "llm_model": session.get("llm_model"),
        "llm_backup_used": bool(session.get("llm_backup_used", False)),
    }
    store.save("meta", meta)

    try:
        step1_data = _compute_step1(store)
    except Exception as exc:
        _logger.exception("Steps 1-2 (segmentation and abstraction) failed")
        return redirect(f"/upload?llm_error={_urlquote(str(exc))}")
    store.save_step(1, step1_data)

    # If no model had been recorded, step 1's client decided it; keep that for step 3.
    meta["llm_model"] = step1_data.get("llm_model")
    meta["llm_backup_used"] = bool(step1_data.get("llm_backup_used", False))
    store.save("meta", meta)

    history_entry = {
        "id": history_id,
        "timestamp": datetime.now().isoformat(),
        "filename": filename,
        "event_column": event_column,
        "progressive_aid": aid,
        "activity_count": 0,
        # Which model produced this analysis (for attribution in results and history).
        "llm_model": meta["llm_model"],
        "llm_backup_used": meta["llm_backup_used"],
    }
    with _history_lock:
        history = _get_history()
        history.insert(0, history_entry)
        _save_history(history)

    return redirect(f"/workspace/{history_id}#segment")


@bp.route("/<aid>/normalise/start", methods=["POST"])
def normalise_start(aid):
    if not StepStore.exists(aid):
        return jsonify({"error": "not found"}), 404
    store = StepStore(aid)
    if store.has_step(2):
        return jsonify({"status": "done"})
    with _step2_lock:
        state = _step2_progress.get(aid, {})
        if state.get("status") == "computing":
            return jsonify({"status": "computing", "completed": state.get("completed", 0),
                            "total": state.get("total", 0)})
        _step2_progress[aid] = {"status": "computing", "completed": 0, "total": 0}
    threading.Thread(target=_run_step2_thread, args=(aid,), daemon=True).start()
    return jsonify({"status": "started"})


@bp.route("/<aid>/normalise/poll")
def normalise_poll(aid):
    if StepStore.exists(aid) and StepStore(aid).has_step(2):
        return jsonify({"status": "done"})
    with _step2_lock:
        state = dict(_step2_progress.get(aid, {"status": "waiting"}))
    return jsonify(state)
