"""Blueprint for the progressive step-by-step analysis interface."""

import os
import threading
import uuid

from flask import (
    Blueprint, jsonify, redirect, render_template,
    request, url_for
)
from werkzeug.utils import secure_filename

from .step_store import StepStore

bp = Blueprint("progressive", __name__, url_prefix="/p")

STEP_TITLES = {
    1: "Event Grouping",
    2: "Activity Naming",
    3: "Action / Object Extraction",
    4: "Pattern Matching",
    5: "Context Identification",
    6: "Method Recommendation",
}

# ── Async state for step 2 (LLM) ─────────────────────────────────────────────

_step2_lock = threading.Lock()
_step2_progress: dict = {}  # aid -> {status, completed, total, error}


# ── Object reconstruction helpers ─────────────────────────────────────────────

def _reconstruct_events(serialized: list):
    from src.models.event import Event
    return [Event(e["event"], e.get("attributes", {}), e.get("row_index")) for e in serialized]


def _reconstruct_groups(step1: dict):
    from src.inference.event_grouper import EventGroup
    result = []
    for g in step1["groups"]:
        result.append(EventGroup(
            events=_reconstruct_events(g["events"]),
            is_context_switch=g.get("is_context_switch", False),
            previous_app=g.get("previous_app"),
            current_app=g.get("current_app"),
        ))
    return result


def _reconstruct_activities(step2: dict):
    from src.models.activity import Activity
    result = []
    for a in step2["activities"]:
        result.append(Activity(
            name=a["name"],
            confidence=a["confidence"],
            evidence=a.get("evidence", []),
            reasoning=a.get("reasoning", ""),
            source_events=a.get("source_events", []),
            activity_type=a.get("activity_type", "main"),
            is_implicit=a.get("is_implicit", False),
            group_index=a.get("group_index", 0),
            pattern_name=a.get("pattern_name"),
        ))
    return result


def _serialize_activity(a) -> dict:
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
    }


# ── Step compute functions ────────────────────────────────────────────────────

def _compute_step1(store: StepStore) -> dict:
    from src.parser.csv_loader import CSVLoader
    from src.inference.event_grouper import EventGrouper
    from src.llm.client import get_llm_client

    meta = store.load("meta")
    llm_client = get_llm_client()
    loader = CSVLoader(llm_client)
    if meta.get("event_column"):
        loader._force_column = meta["event_column"]

    events = loader.load(meta["filepath"])

    grouper = EventGrouper()
    if loader.detected_group_columns:
        grouper.group_attributes = loader.detected_group_columns
    if loader.detected_switch_columns:
        grouper.context_switch_attributes = loader.detected_switch_columns

    groups = grouper.group_events_with_context_switches(events)

    serialized = []
    for i, g in enumerate(groups):
        serialized.append({
            "group_index": i,
            "events": [{"event": e.event, "row_index": e.row_index, "attributes": e.attributes}
                       for e in g.events],
            "is_context_switch": g.is_context_switch,
            "previous_app": g.previous_app,
            "current_app": g.current_app,
        })

    return {
        "groups": serialized,
        "group_count": len(groups),
        "event_count": sum(len(g.events) for g in groups),
    }


def _run_step2(aid: str) -> None:
    """Run LLM activity naming in a background thread and save to store."""
    store = StepStore(aid)
    try:
        from src.inference.activity_inferrer import ActivityInferrer
        from src.matching import PATTERNS
        from src.llm.client import get_llm_client

        step1 = store.load_step(1)
        groups = _reconstruct_groups(step1)
        total = len(groups)

        with _step2_lock:
            _step2_progress[aid] = {"status": "computing", "completed": 0, "total": total}

        def _on_progress(completed, total):
            with _step2_lock:
                _step2_progress[aid].update({"completed": completed, "total": total})

        llm_client = get_llm_client()
        inferrer = ActivityInferrer(llm_client, progress_callback=_on_progress, patterns=PATTERNS)
        activities = inferrer.infer_activities(groups)

        store.save_step(2, {"activities": [_serialize_activity(a) for a in activities]})

        with _step2_lock:
            _step2_progress[aid]["status"] = "done"

    except Exception as exc:
        with _step2_lock:
            _step2_progress[aid] = {"status": "error", "error": str(exc)}


def _compute_step3(store: StepStore) -> dict:
    """Action/Object Extraction + Context Identification (both rule-based)."""
    from src.matching.pattern_matcher import PatternMatcher, get_context_from_events
    from src.matching import PATTERNS

    step1 = store.load_step(1)
    step2 = store.load_step(2)
    activities = _reconstruct_activities(step2)
    matcher = PatternMatcher(PATTERNS)

    # Precompute context per group (needed by step 4 and 5)
    contexts = []
    for g in step1["groups"]:
        group_events = _reconstruct_events(g["events"])
        contexts.append({
            "group_index": g["group_index"],
            "environment": get_context_from_events(group_events),
        })
    ctx_by_group = {c["group_index"]: c["environment"] for c in contexts}

    pairs = []
    for i, a in enumerate(activities):
        group_idx = a.group_index
        group_events = (
            _reconstruct_events(step1["groups"][group_idx]["events"])
            if group_idx < len(step1["groups"]) else []
        )
        raw_action, raw_obj = (a.name.split(" ", 1) if " " in a.name else (a.name, ""))
        norm_action, norm_obj = matcher._normalize_activity(raw_action, raw_obj, group_events)

        pairs.append({
            "activity_index": i,
            "activity_name": a.name,
            "raw_action": raw_action,
            "raw_object": raw_obj,
            "norm_action": norm_action,
            "norm_object": norm_obj,
            "activity_type": a.activity_type,
            "is_implicit": a.is_implicit,
            "group_index": group_idx,
            "environment": ctx_by_group.get(group_idx, "unknown"),
        })

    return {"pairs": pairs, "contexts": contexts}


def _compute_step4(store: StepStore) -> dict:
    """Pattern Matching."""
    from src.matching.pattern_matcher import PatternMatcher
    from src.matching import PATTERNS

    step1 = store.load_step(1)
    step2 = store.load_step(2)
    step3 = store.load_step(3)
    activities = _reconstruct_activities(step2)
    ctx_by_group = {c["group_index"]: c["environment"] for c in step3["contexts"]}
    matcher = PatternMatcher(PATTERNS)

    matches = []
    for a in activities:
        group_idx = a.group_index
        group_events = (
            _reconstruct_events(step1["groups"][group_idx]["events"])
            if group_idx < len(step1["groups"]) else []
        )
        context = ctx_by_group.get(group_idx, "unknown")
        pattern = matcher.match(a, group_events, context)

        matches.append({
            "activity_name": a.name,
            "activity_action": pattern.action if pattern else None,
            "pattern_name": pattern.name if pattern else None,
            "method_category": pattern.category if pattern else None,
            "activity_type": a.activity_type,
            "is_implicit": a.is_implicit,
            "group_index": group_idx,
            "source_events": a.source_events,
        })

    return {"matches": matches}


def _compute_step5(store: StepStore) -> dict:
    """Context Identification — reads contexts already computed in step 3."""
    step3 = store.load_step(3)
    return {"contexts": step3["contexts"]}


def _compute_step6(store: StepStore) -> dict:
    """Method Recommendation."""
    from src.matching.pattern_matcher import PatternMatcher
    from src.matching import PATTERNS

    step1 = store.load_step(1)
    step2 = store.load_step(2)
    step3 = store.load_step(3)
    activities = _reconstruct_activities(step2)
    ctx_by_group = {c["group_index"]: c["environment"] for c in step3["contexts"]}
    matcher = PatternMatcher(PATTERNS)

    recommendations = []
    for a in activities:
        group_idx = a.group_index
        group_events = (
            _reconstruct_events(step1["groups"][group_idx]["events"])
            if group_idx < len(step1["groups"]) else []
        )
        context = ctx_by_group.get(group_idx, "unknown")
        pattern = matcher.match(a, group_events, context)
        method = pattern.get_method_for_context(context) if pattern else None
        raw_action = a.name.split()[0] if a.name else ""
        raw_obj = " ".join(a.name.split()[1:]) if " " in a.name else ""

        recommendations.append({
            "activity_name": a.name,
            "activity_action": pattern.action if pattern else raw_action,
            "activity_object": raw_obj,
            "pattern_matched": pattern.name if pattern else None,
            "execution_environment": context,
            "method": method,
            "method_category": pattern.category if pattern else None,
            "confidence": a.confidence,
            "events": a.source_events,
            "activity_type": a.activity_type,
            "is_implicit": a.is_implicit,
            "context_switch": a.activity_type == "context_switch",
        })

    return {"recommendations": recommendations}


_COMPUTE = {
    1: _compute_step1,
    3: _compute_step3,
    4: _compute_step4,
    5: _compute_step5,
    6: _compute_step6,
}


# ── Routes ────────────────────────────────────────────────────────────────────

@bp.route("/upload", methods=["GET", "POST"])
def upload():
    if request.method == "POST":
        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400
        f = request.files["file"]
        if not f.filename or not f.filename.endswith(".csv"):
            return jsonify({"error": "Only CSV files are allowed"}), 400

        aid = str(uuid.uuid4())
        filename = secure_filename(f.filename)
        upload_dir = os.path.join("data", "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        filepath = os.path.join(upload_dir, f"{aid}_{filename}")
        f.save(filepath)

        store = StepStore(aid)
        store.save("meta", {"aid": aid, "filename": filename, "filepath": filepath, "event_column": None})

        return jsonify({"aid": aid})

    return render_template("progressive/upload.html")


@bp.route("/<aid>/column", methods=["GET", "POST"])
def column(aid):
    if not StepStore.exists(aid):
        return redirect(url_for("progressive.upload"))
    store = StepStore(aid)
    meta = store.load("meta")

    if request.method == "POST":
        meta["event_column"] = request.form.get("event_column") or None
        store.save("meta", meta)
        return redirect(url_for("progressive.step", aid=aid, step_num=1))

    # Detect columns and LLM suggestion
    try:
        import csv as _csv
        columns, rows = [], []
        with open(meta["filepath"], newline="", encoding="utf-8-sig") as fh:
            reader = _csv.DictReader(fh)
            columns = reader.fieldnames or []
            for i, row in enumerate(reader):
                if i >= 10:
                    break
                rows.append(dict(row))

        detected = None
        try:
            from src.llm.client import get_llm_client
            from src.parser.csv_loader import CSVLoader
            llm_client = get_llm_client()
            loader = CSVLoader(llm_client)
            detected = loader._detect_event_column_with_llm(columns, sample_rows=rows)
        except Exception:
            pass

    except Exception as exc:
        return f"Error reading file: {exc}", 500

    return render_template(
        "progressive/column.html",
        aid=aid, meta=meta, columns=columns, rows=rows, detected=detected,
    )


@bp.route("/<aid>/step/<int:step_num>")
def step(aid, step_num):
    if step_num not in range(1, 7):
        return redirect(url_for("progressive.step", aid=aid, step_num=1))
    if not StepStore.exists(aid):
        return redirect(url_for("progressive.upload"))

    store = StepStore(aid)

    # Enforce sequential access — redirect back if prerequisite missing
    prereq = "meta" if step_num == 1 else f"step{step_num - 1}"
    if not store.has(prereq):
        target = url_for("progressive.column", aid=aid) if step_num == 1 else url_for("progressive.step", aid=aid, step_num=step_num - 1)
        return redirect(target)

    # Step 2 is async — delegate to its own handler
    if step_num == 2:
        return _handle_step2(aid, store)

    # Compute synchronously if not cached
    if not store.has_step(step_num):
        data = _COMPUTE[step_num](store)
        store.save_step(step_num, data)
    else:
        data = store.load_step(step_num)

    meta = store.load("meta")
    completed_steps = [n for n in range(1, 7) if store.has_step(n)]
    return render_template(
        "progressive/step.html",
        aid=aid, step_num=step_num, data=data, meta=meta,
        step_titles=STEP_TITLES, completed_steps=completed_steps,
    )


def _handle_step2(aid: str, store: StepStore):
    """Render the activity naming step (async LLM)."""
    meta = store.load("meta")
    completed_steps = [n for n in range(1, 7) if store.has_step(n)]

    if store.has_step(2):
        data = store.load_step(2)
        return render_template(
            "progressive/step.html",
            aid=aid, step_num=2, data=data, meta=meta,
            step_titles=STEP_TITLES, completed_steps=completed_steps,
        )

    # Not yet computed — show loading page (JS will trigger /start then poll)
    return render_template(
        "progressive/step2_loading.html",
        aid=aid, meta=meta, step_titles=STEP_TITLES, completed_steps=completed_steps,
    )


@bp.route("/<aid>/step/2/start", methods=["POST"])
def step2_start(aid):
    if not StepStore.exists(aid):
        return jsonify({"error": "analysis not found"}), 404

    store = StepStore(aid)
    if store.has_step(2):
        return jsonify({"status": "done"})

    with _step2_lock:
        state = _step2_progress.get(aid, {})
        if state.get("status") == "computing":
            return jsonify({"status": "computing", "completed": state.get("completed", 0), "total": state.get("total", 0)})

    t = threading.Thread(target=_run_step2, args=(aid,), daemon=True)
    t.start()
    return jsonify({"status": "started"})


@bp.route("/<aid>/step/2/poll")
def step2_poll(aid):
    if StepStore(aid).has_step(2):
        return jsonify({"status": "done"})
    with _step2_lock:
        state = dict(_step2_progress.get(aid, {"status": "waiting"}))
    return jsonify(state)


@bp.route("/<aid>/results")
def results(aid):
    if not StepStore.exists(aid):
        return redirect(url_for("progressive.upload"))
    store = StepStore(aid)
    if not store.has_step(6):
        # Find furthest completed step and redirect there
        for n in range(6, 0, -1):
            if store.has_step(n):
                return redirect(url_for("progressive.step", aid=aid, step_num=n))
        return redirect(url_for("progressive.step", aid=aid, step_num=1))

    data = store.load_step(6)
    meta = store.load("meta")
    completed_steps = list(range(1, 7))
    return render_template(
        "progressive/results.html",
        aid=aid, data=data, meta=meta,
        step_titles=STEP_TITLES, completed_steps=completed_steps,
    )
