"""Progressive (lazy-compute) pipeline — integrates with the existing workspace UI."""

import csv as _csv
import json
import logging
import os
import shutil
import tempfile
import threading
import uuid
from datetime import datetime

_logger = logging.getLogger(__name__)

from urllib.parse import quote as _urlquote

from flask import Blueprint, jsonify, redirect, request, session

from .step_store import StepStore

bp = Blueprint("progressive", __name__, url_prefix="/p")

PROGRESSIVE_STAGE_KEYS = (
    "event_grouping",
    "activity_naming",
    "action_object_extraction",
    "pattern_matching",
    "context_determination",
    "method_recommendation",
)

PROGRESSIVE_LOGIC = {
    "event_grouping": (
        "• Grouping Criterion: Consecutive events are placed in the same group when they share at least one "
        "context attribute — such as the active application name, webpage URL, or element identifier — indicating "
        "they belong to the same interaction unit within the log.\n"
        "• Context Switch Detection: When the application attribute changes between two consecutive events, the "
        "current group closes and a new group begins. This boundary marks an environment transition in the log "
        "and is later surfaced as an explicit Switch Context activity during activity inference.\n"
        "• Group Scope: Each group represents one contiguous interaction unit. Its size (number of events) "
        "reflects the complexity of that interaction. Groups are the primary input to activity inference: "
        "one group produces one inferred activity name."
    ),
    "activity_naming": (
        "• Activity Labeling: Each event group is sent to an LLM which interprets the interaction intent and assigns a natural language activity name "
        "(e.g., 'Write data into a textfield') rather than describing low-level events.\n"
        "• Prerequisite Activities: When an activity targets a specific UI element, an implicit 'Find <element>' activity is inserted before it, "
        "reflecting the RPA requirement to locate an element before interacting with it.\n"
        "• Context Switches: When the application context changes between groups (e.g., from Excel to a browser), an implicit "
        "'Switch context from X to Y' activity is inserted to explicitly represent the environment transition."
    ),
    "action_object_extraction": (
        "• Action Identification — Semantic Mapping to AOMC Vocabulary: "
        "UI logs record raw interaction verbs that are application-specific or tool-specific "
        "(e.g., 'click', 'paste', 'changeField', 'typeKeys', 'getCell', 'startPage'). "
        "These log-level terms are semantically mapped to the canonical Action vocabulary defined by the "
        "Action-Object-Method-Context (AOMC) framework. "
        "The mapping resolves surface variants and synonyms to a single shared AOMC term — for example: "
        "'click', 'press', and 'tap' from the log → AOMC Activate; "
        "'write', 'paste', 'type', 'fill', and 'changeField' from the log → AOMC Write/Input/Update/Modify; "
        "'find' and 'identify' from the log → AOMC Find/Identify; "
        "'read', 'extract', and 'getCell' from the log → AOMC Read/Extract; "
        "'open', 'run', and 'launch' from the log → AOMC Open/Run; "
        "'navigate' and 'switch' from the log → AOMC Switch context. "
        "The AOMC framework defines 13 canonical actions across three categories: "
        "Extraction (Find/Identify, Read/Extract, Observe), "
        "Modification (Write/Input/Update/Modify, Delete/Remove, Disable/Hide), and "
        "Control (Open/Run, Activate, Hover, Switch context, Scroll, Focus, Refresh). "
        "Each mapped action is assigned to its AOMC category to characterise the bot's interaction intent at design level.\n"
        "• Object Identification — Mapping to AOMC UI Element: "
        "UI logs capture target elements through raw attributes such as tag names (e.g., 'input', 'button', 'textarea'), "
        "element identifiers (e.g., 'username', 'submit-btn'), XPath expressions, or spreadsheet references (e.g., 'B2:B4'). "
        "These raw attributes are assembled into the element descriptor during activity inference, "
        "then isolated here by stripping context qualifiers — URL, page path, and application name — "
        "that describe where the interaction occurs rather than what is acted upon. "
        "The remaining descriptor (e.g., 'textfield \\'username\\'', 'button \\'submit\\'', 'cell range B2:B4') "
        "corresponds to the AOMC Object: the interface element upon which the action is performed."
    ),
    "pattern_matching": (
        "• Action-Based Candidate Selection: The AOMC action extracted in the previous stage is compared against "
        "each of the 13 RPA UI Interaction patterns' recognised action vocabularies. Patterns whose action list "
        "includes the activity's AOMC action are selected as candidates (e.g., AOMC 'Write/Input/Update/Modify' "
        "→ candidate: Write Element pattern).\n"
        "• Context Filtering: Candidate patterns are filtered by the execution environment determined for the "
        "activity. Only patterns whose defined contexts include the current environment (web, desktop, or screen) "
        "are eligible for selection.\n"
        "• First-Match Rule: The first eligible pattern in catalogue order is selected as the matched pattern. "
        "The matched pattern constrains the automation method: only the methods defined within that pattern's "
        "context-method mapping are valid recommendations for the activity."
    ),
    "context_determination": (
        "• Attribute-Based Environment Inference: Each activity group is examined for context-related CSV "
        "attributes — such as a browser URL or XPath (indicating a web environment), an application name or "
        "workbook reference (indicating a desktop environment), or screen coordinates (indicating a screen "
        "environment). The first matching attribute found determines the execution environment.\n"
        "• Priority Rule: Web indicators take precedence over desktop indicators, which take precedence over "
        "screen indicators. This priority reflects the method fidelity hierarchy: DOM-level methods are more "
        "reliable than UI Automation methods, which in turn are more reliable than visual recognition.\n"
        "• Deciding Attributes: Only the attributes that actually drove the environment decision are shown — "
        "not all attributes present in the group. This makes it explicit which evidence was used and allows "
        "analysts to verify or override the inferred context."
    ),
    "method_recommendation": (
        "• Pattern-Driven Method Lookup: The automation method is drawn from the matched pattern's "
        "context-method mapping for the activity's execution environment. Each pattern defines one method "
        "per supported context (e.g., Write Element in web → DOM Manipulation; in desktop → UI Automation "
        "Manipulation; in screen → Hardware Simulation).\n"
        "• Priority Ordering: When multiple activities are compared, methods are ranked by fidelity: "
        "DOM-level methods (content-level) rank highest, followed by UI Automation methods (accessibility-level), "
        "followed by visual recognition and hardware simulation (input-level). Higher-fidelity methods are "
        "preferred because they are more robust to UI changes and less error-prone.\n"
        "• One Recommendation per Activity: A single method is recommended per activity — the highest-priority "
        "method available for the matched pattern and context. Analysts may override this recommendation on the "
        "Analysis Results page if a different method better suits the deployment constraints."
    ),
}

# ── Async state for activity naming (LLM) ────────────────────────────────────
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
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=dir_path,
                                     delete=False, suffix=".tmp") as f:
        json.dump(history, f, indent=2)
        tmp_path = f.name
    os.replace(tmp_path, path)


def _update_history_stage(history_id, stage_key, workspace_data):
    with _history_lock:
        history = _get_history()
        for entry in history:
            if entry["id"] == history_id:
                entry["progressive_artifacts"][stage_key] = workspace_data
                break
        _save_history(history)


def _update_history_dfg(history_id, dfg):
    with _history_lock:
        history = _get_history()
        for entry in history:
            if entry["id"] == history_id:
                entry["dfg"] = dfg
                break
        _save_history(history)


# ── CSV preview helper ────────────────────────────────────────────────────────

def _read_csv_preview(filepath, max_rows=100):
    from src.parser.csv_loader import CSVLoader
    with open(filepath, "r", encoding="utf-8-sig", newline="") as f:
        reader = _csv.reader(f)
        raw_headers = next(reader, [])
        headers = CSVLoader._dedup_headers(raw_headers)
        rows = []
        for i, vals in enumerate(reader):
            if i >= max_rows:
                break
            rows.append({h: (vals[j] if j < len(vals) else "") for j, h in enumerate(headers)})
    return headers, rows


# ── Context attribute picker (mirrors app.py logic) ───────────────────────────

_WEB_ATTRS = ["xpath", "xpath_full", "html_id", "tag_name", "tag_type",
              "tag_html", "tag_href", "browser_url", "webpage", "url"]
_DESKTOP_ATTRS = ["application", "app", "window_title", "workbook",
                  "worksheet", "cell_range", "control_type", "ui_path"]
_SCREEN_ATTRS = ["x", "y", "mouse_x", "mouse_y", "click_x", "click_y",
                 "coordinates", "coordinate"]


def _pick_deciding_attributes(env, unique_attr_vals):
    def _first_present(candidates):
        for attr in candidates:
            val = (unique_attr_vals.get(attr) or [None])[0]
            if val not in (None, "", "None", "none"):
                return {attr: val}
        return {}
    if env == "web":
        return _first_present(_WEB_ATTRS)
    if env == "desktop":
        result = _first_present(["application", "app"])
        result.update(_first_present(["window_title", "workbook", "worksheet"]))
        return result
    if env == "screen":
        return _first_present(_SCREEN_ATTRS)
    return {}


# ── Object reconstruction helpers ─────────────────────────────────────────────

def _reconstruct_events(serialized):
    from src.models.event import Event
    return [Event(e["event"], e.get("attributes", {}), e.get("row_index")) for e in serialized]


def _reconstruct_groups(step1):
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


def _reconstruct_activities(step2):
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
    }


# ── Workspace-format converters ───────────────────────────────────────────────

def _ws_event_grouping(step1):
    return {
        "groups": [
            {
                "group_index": g["group_index"],
                "event_rows": [e["row_index"] for e in g["events"] if e.get("row_index") is not None],
                "event_labels": [e["event"] for e in g["events"]],
                "group_size": len(g["events"]),
            }
            for g in step1["groups"]
        ]
    }


def _ws_activity_naming(step2):
    return {
        "activities": [
            {
                "activity_index": i,
                "group_index": a.get("group_index", 0),
                "activity_name": a["name"],
                "activity_type": a.get("activity_type", "main"),
                "is_implicit": a.get("is_implicit", False),
                "confidence": a["confidence"],
                "source_events": a.get("source_events", []),
                "evidence": a.get("evidence", []),
            }
            for i, a in enumerate(step2["activities"])
        ]
    }


def _ws_action_object_extraction(step2, step3):
    return {
        "pairs": [
            {
                "activity_index": p["activity_index"],
                "group_index": p.get("group_index", 0),
                "activity_name": p["activity_name"],
                "activity_type": p.get("activity_type", "main"),
                "is_implicit": p.get("is_implicit", False),
                "activity_action": p["norm_action"],
                "activity_object": p["norm_object"],
            }
            for p in step3["pairs"]
        ]
    }


def _ws_pattern_matching(step3, step4):
    ctx_by_group = {c["group_index"]: c["environment"] for c in step3["contexts"]}
    return {
        "matches": [
            {
                "inferred_activity": m["activity_name"],
                "execution_environment": ctx_by_group.get(m.get("group_index", -1), "unknown"),
                "pattern_matched": m.get("pattern_name"),
                "method_category": m.get("method_category"),
                "events": m.get("source_events", []),
            }
            for m in step4["matches"]
        ]
    }


def _ws_context_determination(step1, step2, step3):
    groups_by_idx = {g["group_index"]: g for g in step1["groups"]}
    env_by_group = {c["group_index"]: c["environment"] for c in step3["contexts"]}

    contexts = []
    for a in step2["activities"]:
        group_idx = a.get("group_index", 0)
        group = groups_by_idx.get(group_idx, {})
        env = env_by_group.get(group_idx, "unknown")

        unique_attr_vals = {}
        for e in group.get("events", []):
            for k, v in e.get("attributes", {}).items():
                sv = str(v) if v is not None else ""
                if sv:
                    unique_attr_vals.setdefault(k, [])
                    if sv not in unique_attr_vals[k]:
                        unique_attr_vals[k].append(sv)

        context_attr_values = _pick_deciding_attributes(env, unique_attr_vals)
        is_ctx_switch = a.get("activity_type", "main") == "context_switch"

        contexts.append({
            "inferred_activity": a["name"],
            "execution_environment": env,
            "context_attributes_used": list(context_attr_values.keys()),
            "context_attribute_values": context_attr_values,
            "context_switch": is_ctx_switch,
            "context_switch_from": group.get("previous_app") if is_ctx_switch else None,
            "context_switch_to": group.get("current_app") if is_ctx_switch else None,
        })

    return {"contexts": contexts}


def _ws_method_recommendation(step2, step6):
    return {
        "recommendations": [
            {
                "inferred_activity": r["activity_name"],
                "recommended_method": r.get("method"),   # workspace.html key
                "method": r.get("method"),               # results.html key
                "activity_action": r.get("activity_action", ""),
                "activity_object": r.get("activity_object", ""),
                "execution_environment": r.get("execution_environment", ""),
                "pattern_matched": r.get("pattern_matched"),
                "method_category": r.get("method_category"),
                "confidence": r.get("confidence"),
                "events": r.get("events", []),
                "context_switch": r.get("context_switch", False),
                "activity_type": r.get("activity_type", "main"),
                "is_implicit": r.get("is_implicit", False),
            }
            for r in step6["recommendations"]
        ]
    }


def _to_workspace(store, stage_key):
    """Convert StepStore data to the workspace progressive_artifacts format."""
    if stage_key == "event_grouping":
        return _ws_event_grouping(store.load_step(1))
    if stage_key == "activity_naming":
        return _ws_activity_naming(store.load_step(2))
    if stage_key == "action_object_extraction":
        return _ws_action_object_extraction(store.load_step(2), store.load_step(3))
    if stage_key == "pattern_matching":
        return _ws_pattern_matching(store.load_step(3), store.load_step(4))
    if stage_key == "context_determination":
        return _ws_context_determination(store.load_step(1), store.load_step(2), store.load_step(3))
    if stage_key == "method_recommendation":
        return _ws_method_recommendation(store.load_step(2), store.load_step(6))
    return {}


# ── Step compute functions ────────────────────────────────────────────────────

def _compute_step1(store):
    from src.parser.csv_loader import CSVLoader
    from src.inference.event_grouper import EventGrouper, LLMGroupRefiner
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

    refiner = LLMGroupRefiner(llm_client)
    groups = refiner.refine(groups)

    serialized = [
        {
            "group_index": i,
            "events": [{"event": e.event, "row_index": e.row_index, "attributes": e.attributes}
                       for e in g.events],
            "is_context_switch": g.is_context_switch,
            "previous_app": g.previous_app,
            "current_app": g.current_app,
        }
        for i, g in enumerate(groups)
    ]
    return {"groups": serialized, "group_count": len(groups),
            "event_count": sum(len(g.events) for g in groups)}


def _run_step2_thread(aid):
    store = StepStore(aid)
    try:
        from src.inference.activity_inferrer import ActivityInferrer
        from src.matching import PATTERNS
        from src.llm.client import get_llm_client

        step1 = store.load_step(1)
        groups = _reconstruct_groups(step1)
        total = len(groups)

        with _step2_lock:
            _step2_progress[aid].update({"total": total})

        def _on_progress(completed, total):
            with _step2_lock:
                _step2_progress[aid].update({"completed": completed, "total": total})

        llm_client = get_llm_client()
        inferrer = ActivityInferrer(llm_client, progress_callback=_on_progress, patterns=PATTERNS)
        activities = inferrer.infer_activities(groups)
        if not activities:
            raise RuntimeError("Activity naming produced no results — LLM may be unavailable.")

        store.save_step(2, {"activities": [_serialize_activity(a) for a in activities]})

        meta = store.load("meta")
        _update_history_stage(meta["history_id"], "activity_naming",
                              _ws_activity_naming(store.load_step(2)))

        with _step2_lock:
            _step2_progress[aid]["status"] = "done"

    except Exception as exc:
        with _step2_lock:
            _step2_progress[aid] = {"status": "error", "error": str(exc)}


def _compute_step3(store):
    from src.matching.pattern_matcher import get_context_from_events
    from src.matching import PATTERNS

    step1 = store.load_step(1)
    step2 = store.load_step(2)
    activities = _reconstruct_activities(step2)

    patterns_by_name = {p.name.lower(): p for p in PATTERNS}

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
        pattern = patterns_by_name.get((a.pattern_name or "").strip().lower())
        pairs.append({
            "activity_index": i,
            "activity_name": a.name,
            "norm_action": pattern.action if pattern else None,
            "norm_object": pattern.object if pattern else None,
            "activity_type": a.activity_type,
            "is_implicit": a.is_implicit,
            "group_index": group_idx,
            "environment": ctx_by_group.get(group_idx, "unknown"),
        })

    return {"pairs": pairs, "contexts": contexts}


def _compute_step4(store):
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
        # Context switches are OS-level operations; the Switch Context pattern
        # only lists "desktop", so force that context for matching purposes.
        match_context = "desktop" if a.activity_type == "context_switch" else context
        pattern = matcher.match(a, group_events, match_context)
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


def _compute_step6(store):
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
        match_context = "desktop" if a.activity_type == "context_switch" else context
        pattern = matcher.match(a, group_events, match_context)
        method = pattern.get_method_for_context(match_context) if pattern else None

        recommendations.append({
            "activity_name": a.name,
            "activity_action": pattern.action if pattern else None,
            "activity_object": pattern.object if pattern else None,
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


def _compute_dfg(store):
    """Build the Directly-Follows Graph from the inferred activity sequence.

    Mirrors the activity sequence the workspace shows (step 2 activities,
    including implicit Find/Switch steps), in temporal order.
    """
    from src.process_mining import build_dfg_payload

    meta = store.load("meta")
    activities = _reconstruct_activities(store.load_step(2))

    class _EvShim:
        def __init__(self, row_index):
            self.row_index = row_index
            self.attributes = {}

    class _MapShim:
        def __init__(self, activity):
            self.activity = activity
            self.events = [_EvShim(r) for r in (activity.source_events or [])]

    mappings = [_MapShim(a) for a in activities]
    return build_dfg_payload(mappings, session_id=meta.get("history_id") or meta["aid"])


_STAGE_TO_STEP = {
    "action_object_extraction": 3,
    "pattern_matching": 4,
    "context_determination": 3,  # reads from step 3 contexts
    "method_recommendation": 6,
}

_STEP_COMPUTE_FNS = {3: _compute_step3, 4: _compute_step4, 6: _compute_step6}

_STEP_DEPS = {
    "action_object_extraction": [3],
    "pattern_matching": [3, 4],
    "context_determination": [3],
    "method_recommendation": [3, 6],
}


def _ensure_dependencies(store, stage_key):
    """Auto-compute any missing prerequisite steps (steps 3, 4, 6 only)."""
    for step_num in _STEP_DEPS.get(stage_key, []):
        if not store.has_step(step_num):
            data = _STEP_COMPUTE_FNS[step_num](store)
            store.save_step(step_num, data)


# ── Routes ────────────────────────────────────────────────────────────────────

@bp.route("/start-progressive")
def start_progressive():
    """Entry point: compute step 1 from the session file and redirect to workspace."""
    filepath = session.get("uploaded_file")
    filename = session.get("filename")
    if not filepath or not os.path.exists(filepath):
        return redirect("/upload")

    event_column = request.args.get("event_column")
    aid = str(uuid.uuid4())
    history_id = str(uuid.uuid4())

    os.makedirs(os.path.join("data", "uploads"), exist_ok=True)
    prog_filepath = os.path.join("data", "uploads", f"{aid}_{filename}")
    shutil.copy2(filepath, prog_filepath)

    store = StepStore(aid)
    store.save("meta", {
        "aid": aid,
        "history_id": history_id,
        "filename": filename,
        "filepath": prog_filepath,
        "event_column": event_column,
    })

    try:
        step1_data = _compute_step1(store)
    except Exception as exc:
        _logger.exception("Step 1 (event grouping / column detection) failed")
        return redirect(f"/upload?llm_error={_urlquote(str(exc))}")
    store.save_step(1, step1_data)

    try:
        log_columns, preview_rows = _read_csv_preview(prog_filepath)
        log_preview = [{"row_index": i, "values": row} for i, row in enumerate(preview_rows)]
    except Exception:
        log_columns, log_preview = [], []

    progressive_artifacts = {k: {} for k in PROGRESSIVE_STAGE_KEYS}
    progressive_artifacts["event_grouping"] = _ws_event_grouping(step1_data)

    history_entry = {
        "id": history_id,
        "timestamp": datetime.now().isoformat(),
        "filename": filename,
        "activities": [],
        "recommendations": [],
        "dfg": {},
        "progressive_artifacts": progressive_artifacts,
        "progressive_logic": PROGRESSIVE_LOGIC,
        "event_column": event_column,
        "log_columns": log_columns,
        "log_preview": log_preview,
        "progressive_aid": aid,
    }

    with _history_lock:
        history = _get_history()
        history.insert(0, history_entry)
        _save_history(history)

    return redirect(f"/workspace/{history_id}#event_grouping")


@bp.route("/<aid>/compute/activity_naming/start", methods=["POST"])
def activity_naming_start(aid):
    if not StepStore.exists(aid):
        return jsonify({"error": "not found"}), 404
    store = StepStore(aid)
    if store.has_step(2):
        return jsonify({"status": "done"})
    with _step2_lock:
        state = _step2_progress.get(aid, {})
        if state.get("status") == "computing":
            return jsonify({"status": "computing",
                            "completed": state.get("completed", 0),
                            "total": state.get("total", 0)})
        _step2_progress[aid] = {"status": "computing", "completed": 0, "total": 0}
    t = threading.Thread(target=_run_step2_thread, args=(aid,), daemon=True)
    t.start()
    return jsonify({"status": "started"})


@bp.route("/<aid>/compute/activity_naming/poll")
def activity_naming_poll(aid):
    if StepStore(aid).has_step(2):
        return jsonify({"status": "done"})
    with _step2_lock:
        state = dict(_step2_progress.get(aid, {"status": "waiting"}))
    return jsonify(state)


@bp.route("/<aid>/compute/<stage_key>")
def compute_stage(aid, stage_key):
    """Synchronously compute a pipeline stage, update history, redirect to workspace."""
    if stage_key == "activity_naming":
        return jsonify({"error": "use async endpoint"}), 400
    if stage_key not in PROGRESSIVE_STAGE_KEYS:
        return "Unknown stage", 400
    if not StepStore.exists(aid):
        return redirect("/upload")

    store = StepStore(aid)
    meta = store.load("meta")
    history_id = meta["history_id"]

    # All stages after event_grouping need activity naming (step 2) to be done first
    if stage_key != "event_grouping" and not store.has_step(2):
        return redirect(f"/workspace/{history_id}#activity_naming")

    # Compute every stage in order from action_object_extraction up to the
    # requested stage. This ensures no intermediate stage is skipped when the
    # user jumps ahead in the roadmap.
    try:
        stage_idx = PROGRESSIVE_STAGE_KEYS.index(stage_key)
        computed = PROGRESSIVE_STAGE_KEYS[2:stage_idx + 1]
        for sk in computed:
            _ensure_dependencies(store, sk)
            ws_data = _to_workspace(store, sk)
            _update_history_stage(history_id, sk, ws_data)
        # The DFG reflects the full activity sequence, so build it once the
        # final method_recommendation stage has been computed.
        if "method_recommendation" in computed:
            _update_history_dfg(history_id, _compute_dfg(store))
    except Exception as exc:
        _logger.exception("Stage %s computation failed", stage_key)
        return redirect(f"/workspace/{history_id}?llm_error={_urlquote(str(exc))}#{stage_key}")

    return redirect(f"/workspace/{history_id}#{stage_key}")
