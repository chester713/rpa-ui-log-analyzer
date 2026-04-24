"""Flask web application for RPA UI Log Analyzer."""

import os
import json
import uuid
import csv
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "data/uploads"
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or os.urandom(32).hex()
app.config["JSON_SORT_KEYS"] = False
app.json.sort_keys = False

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs("config", exist_ok=True)
os.makedirs("data", exist_ok=True)
os.makedirs("skills", exist_ok=True)

DEFAULT_LLM_CONFIG = {
    "provider": "puter",
    "endpoint": "",
    "api_key": "",
    "model": "gpt-4o-mini",
}

MAX_PREVIEW_ROWS = 100
MAX_HISTORY_ENTRIES = 200
PROGRESSIVE_STAGE_KEYS = (
    "event_grouping",
    "activity_naming",
    "action_object_extraction",
    "pattern_matching",
    "context_determination",
    "method_recommendation",
)
SENSITIVE_FIELD_TOKENS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
)


def _mask_api_key(api_key: str) -> str:
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return f"{api_key[:4]}...{api_key[-4:]}"


def _is_masked_api_key(value: str) -> bool:
    return bool(value) and ("..." in value or set(value) == {"*"})


def _redact_row(row: dict) -> dict:
    redacted = {}
    for key, value in (row or {}).items():
        key_l = str(key or "").lower()
        if any(token in key_l for token in SENSITIVE_FIELD_TOKENS):
            redacted[key] = "[REDACTED]"
        else:
            redacted[key] = value
    return redacted


def _sanitize_config_for_view(config: dict) -> dict:
    safe = dict(config or {})
    safe["api_key"] = _mask_api_key(safe.get("api_key", ""))
    return safe


def _split_action_object(activity_name: str) -> tuple[str, str]:
    if " " in activity_name:
        return activity_name.split(None, 1)
    return activity_name, ""


def _build_progressive_contract(mappings, activities, recommendation_payload, enriched_activities=None):
    grouped_rows = []
    activity_naming = []
    action_object = []

    for idx, mapping in enumerate(mappings):
        row_indices = [e.row_index for e in mapping.events if e.row_index is not None]
        grouped_rows.append(
            {
                "group_index": idx,
                "event_rows": row_indices,
                "event_labels": [str(e.event) for e in mapping.events],
                "group_size": len(mapping.events),
            }
        )

    # Use enriched activities (includes implicit prerequisites and context switches)
    # when available; fall back to the main-only list for backward compatibility.
    naming_source = enriched_activities if enriched_activities is not None else activities

    for idx, activity in enumerate(naming_source):
        action, obj = _split_action_object(activity.name)
        activity_naming.append(
            {
                "activity_index": idx,
                "group_index": getattr(activity, "group_index", idx),
                "activity_name": activity.name,
                "activity_type": getattr(activity, "activity_type", "main"),
                "is_implicit": getattr(activity, "is_implicit", False),
                "confidence": activity.confidence,
                "source_events": activity.source_events,
                "evidence": list(activity.evidence or []),
            }
        )
        action_object.append(
            {
                "activity_index": idx,
                "group_index": getattr(activity, "group_index", idx),
                "activity_name": activity.name,
                "activity_type": getattr(activity, "activity_type", "main"),
                "is_implicit": getattr(activity, "is_implicit", False),
                "activity_action": action,
                "activity_object": obj,
            }
        )

    pattern_matching = []
    context_determination = []
    method_recommendation = []
    for rec in recommendation_payload:
        pattern_matching.append(
            {
                "inferred_activity": rec.get("inferred_activity"),
                "execution_environment": rec.get("execution_environment"),
                "pattern_matched": rec.get("pattern_matched"),
                "method_category": rec.get("method_category"),
                "events": rec.get("events", []),
            }
        )
        context_determination.append(
            {
                "inferred_activity": rec.get("inferred_activity"),
                "execution_environment": rec.get("execution_environment"),
                "context_attributes_used": rec.get("context_attributes_used", []),
                "context_switch": rec.get("context_switch", False),
                "context_switch_from": rec.get("context_switch_from"),
                "context_switch_to": rec.get("context_switch_to"),
            }
        )
        method_recommendation.append(
            {
                "inferred_activity": rec.get("inferred_activity"),
                "recommended_method": rec.get("method"),
                "method_category": rec.get("method_category"),
                "confidence": rec.get("confidence"),
                "events": rec.get("events", []),
            }
        )

    progressive_artifacts = {
        "event_grouping": {"groups": grouped_rows},
        "activity_naming": {"activities": activity_naming},
        "action_object_extraction": {"pairs": action_object},
        "pattern_matching": {"matches": pattern_matching},
        "context_determination": {"contexts": context_determination},
        "method_recommendation": {"recommendations": method_recommendation},
    }

    progressive_logic = {
        "event_grouping": "Events are grouped by shared context and sequential evidence before downstream inference.",
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
            "corresponds to the AOMC Object: the interface element upon which the action is performed. "
            "The AOMC framework categorises objects as HTML elements (web environments, accessed via the DOM), "
            "desktop UI elements (exposed through OS accessibility frameworks such as UI Automation), "
            "or visual elements (identified from screen content via image recognition or OCR)."
        ),
        "pattern_matching": "Activities are compared against known pattern definitions to identify category-level automation strategies.",
        "context_determination": "Execution environment and context attributes are derived from grouped-event metadata to constrain method selection.",
        "method_recommendation": "Final methods are selected from matched patterns, sorted by method priority, and emitted with confidence details.",
    }

    # Preserve deterministic key order for replay contracts.
    progressive_artifacts = {
        stage: progressive_artifacts[stage] for stage in PROGRESSIVE_STAGE_KEYS
    }
    progressive_logic = {stage: progressive_logic[stage] for stage in PROGRESSIVE_STAGE_KEYS}

    return progressive_artifacts, progressive_logic


def get_llm_config():
    config_path = "config/llm_config.json"
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            return json.load(f)
    return DEFAULT_LLM_CONFIG.copy()


def get_inference_rules():
    """Load customizable inference rules from config."""
    path = "config/inference_rules.json"
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"version": "1.0", "rules": []}


def save_llm_config(config):
    config_path = "config/llm_config.json"
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


def get_history():
    history_path = "data/history.json"
    if os.path.exists(history_path):
        try:
            with open(history_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                return loaded if isinstance(loaded, list) else []
        except (json.JSONDecodeError, OSError):
            return []
    return []


def save_history(history):
    history_path = "data/history.json"
    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)


def analyze_csv(filepath):
    from src.parser.csv_loader import CSVLoader
    from src.inference.event_grouper import EventGrouper
    from src.inference.activity_inferrer import ActivityInferrer
    from src.mapping.event_activity_mapper import EventActivityMapper
    from src.pipeline.data_pipeline import DataPipeline
    from src.llm.client import get_llm_client

    llm_client = get_llm_client()
    pipeline = DataPipeline(filepath, llm_client=llm_client)
    result = pipeline.run()
    return result


@app.route("/")
def index():
    return render_template("welcome.html")


@app.route("/upload")
def upload():
    return render_template("index.html")


@app.route("/select-column", methods=["GET", "POST"])
def select_column():
    """Show page for selecting event column after file upload."""
    if request.method == "POST":
        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400

        file = request.files["file"]
        if file.filename == "":
            return jsonify({"error": "No file selected"}), 400

        if not file.filename.endswith(".csv"):
            return jsonify({"error": "Only CSV files are allowed"}), 400

        filename = secure_filename(file.filename)
        filepath = os.path.join(
            app.config["UPLOAD_FOLDER"], f"{uuid.uuid4()}_{filename}"
        )
        file.save(filepath)

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                columns = reader.fieldnames
                rows = []
                for i, row in enumerate(reader):
                    if i < MAX_PREVIEW_ROWS:
                        rows.append(row)

            from src.llm.client import get_llm_client
            from src.parser.csv_loader import CSVLoader

            llm_client = get_llm_client()
            loader = CSVLoader(llm_client)
            detected = loader._detect_event_column_with_llm(
                columns, sample_rows=rows
            )

            session["uploaded_file"] = filepath
            session["filename"] = filename

            return render_template(
                "columns.html",
                columns=columns,
                detected_column=detected,
                rows=rows,
                filename=filename,
            )

        except Exception as e:
            return jsonify({"error": str(e)}), 500

    return redirect("/upload")


@app.route("/detect-column", methods=["POST"])
def detect_column():
    """Detect event column using LLM and return columns for user selection."""
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    if not file.filename.endswith(".csv"):
        return jsonify({"error": "Only CSV files are allowed"}), 400

    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config["UPLOAD_FOLDER"], f"{uuid.uuid4()}_{filename}")
    file.save(filepath)

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            columns = reader.fieldnames

        from src.llm.client import get_llm_client
        from src.parser.csv_loader import CSVLoader

        llm_client = get_llm_client()
        loader = CSVLoader(llm_client)
        preview_rows = []
        with open(filepath, "r", encoding="utf-8") as preview_f:
            preview_reader = csv.DictReader(preview_f)
            for i, row in enumerate(preview_reader):
                if i < 100:
                    preview_rows.append(row)

        detected = loader._detect_event_column_with_llm(
            columns, sample_rows=preview_rows
        )

        session["uploaded_file"] = filepath
        session["filename"] = filename

        return jsonify(
            {
                "columns": columns,
                "detected_column": detected,
                "upload_id": str(uuid.uuid4()),
            }
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/analyze", methods=["POST"])
def analyze():
    data = request.get_json()
    event_column = data.get("event_column") if data else None

    filepath = session.get("uploaded_file")
    filename = session.get("filename")

    if not filepath or not os.path.exists(filepath):
        return jsonify({"error": "No file uploaded"}), 400

    try:
        from src.parser.csv_loader import CSVLoader
        from src.inference.event_grouper import EventGrouper
        from src.inference.activity_inferrer import ActivityInferrer
        from src.mapping.event_activity_mapper import EventActivityMapper
        from src.pipeline.data_pipeline import DataPipeline
        from src.llm.client import get_llm_client

        llm_client = get_llm_client()

        loader = CSVLoader(llm_client)
        if event_column:
            loader._force_column = event_column

        log_columns = []
        log_preview = []
        with open(filepath, "r", encoding="utf-8") as preview_file:
            preview_reader = csv.DictReader(preview_file)
            log_columns = preview_reader.fieldnames or []
            for i, row in enumerate(preview_reader):
                if i < MAX_PREVIEW_ROWS:
                    log_preview.append({"row_index": i, "values": _redact_row(row)})

        events = loader.load(filepath)

        from src.models.activity import Activity, EventActivityMapping

        grouper = EventGrouper()
        inferrer = ActivityInferrer(llm_client)
        mapper = EventActivityMapper(grouper, inferrer)
        mappings = mapper.map(events)
        _post_process = getattr(inferrer, "_post_process_inferred_name", None)
        if _post_process is not None:
            for mapping in mappings:
                mapping.activity.name = _post_process(mapping.activity.name, mapping.events)
        activities = [m.activity for m in mappings]

        from src.matching.pattern_matcher import get_context_from_events, PatternMatcher
        from src.matching import PATTERNS
        from src.models.pattern import MethodRecommendation
        from src.process_mining import build_dfg_payload

        recommendations = []
        matcher = PatternMatcher(PATTERNS)
        context_sequence = []

        def _presence_ratio(events_group, keys):
            total = len(events_group) if events_group else 1
            hits = 0
            present_keys = set()
            for e in events_group:
                attrs = e.attributes or {}
                if any(
                    str(attrs.get(k, "")).strip() not in ["", "None", "none"]
                    for k in keys
                ):
                    hits += 1
                for k in keys:
                    if str(attrs.get(k, "")).strip() not in ["", "None", "none"]:
                        present_keys.add(k)
            return hits / total, sorted(present_keys)

        for mapping in mappings:
            activity = mapping.activity
            events_list = mapping.events

            context = get_context_from_events(events_list)
            context_sequence.append(context)

            pattern = matcher.match(activity, events_list, context)
            method = pattern.get_method_for_context(context) if pattern else None

            event_indices = [
                e.row_index for e in events_list if e.row_index is not None
            ]

            context_switch = mapping.attribute_breakdown.get("context_switch", False)
            context_switch_from = mapping.attribute_breakdown.get("previous_app")
            context_switch_to = mapping.attribute_breakdown.get("current_app")

            action, obj = _split_action_object(activity.name)

            # Confidence model (explicit and explainable)
            # final = 0.60*base + 0.20*context_evidence + 0.10*object_evidence + 0.10*group_consistency + pattern_bonus
            base_conf = float(activity.confidence)
            context_keys = {
                "web": [
                    "browser_url",
                    "url",
                    "tag_name",
                    "tag_type",
                    "xpath",
                    "xpath_full",
                    "category",
                    "application",
                ],
                "desktop": [
                    "application",
                    "workbook",
                    "worksheet",
                    "current_worksheet",
                    "cell_range",
                    "cell_range_number",
                    "event_src_path",
                ],
                "visual": ["screenshot", "mouse_coord", "tag_html"],
            }
            obj_keys = [
                "id",
                "tag_name",
                "tag_type",
                "xpath",
                "xpath_full",
                "cell_range",
                "event_src_path",
            ]

            context_ratio, context_present = _presence_ratio(
                events_list, context_keys.get(context, [])
            )
            object_ratio, object_present = _presence_ratio(events_list, obj_keys)

            # consistency from shared attributes among grouped events
            shared_attrs = (
                mapping.attribute_breakdown.get("shared_attributes", []) or []
            )
            attr_counts = mapping.attribute_breakdown.get("attribute_counts", {}) or {}
            group_consistency = min(1.0, len(shared_attrs) / max(1, len(attr_counts)))

            pattern_bonus = 0.05 if pattern else 0.0
            final_conf = (
                0.60 * base_conf
                + 0.20 * context_ratio
                + 0.10 * object_ratio
                + 0.10 * group_consistency
                + pattern_bonus
            )
            final_conf = max(0.0, min(1.0, round(final_conf, 2)))

            confidence_explanation = (
                "Formula: final = 0.60*base + 0.20*context + 0.10*object + 0.10*consistency + pattern_bonus\n"
                f"base={base_conf:.2f}; context={context_ratio:.2f}; object={object_ratio:.2f}; consistency={group_consistency:.2f}; pattern_bonus={pattern_bonus:.2f}; final={final_conf:.2f}\n"
                f"Context attributes considered ({context}): {', '.join(context_keys.get(context, [])) or 'None'}\n"
                f"Context attributes found in this group: {', '.join(context_present) or 'None'}\n"
                f"Object attributes considered: {', '.join(obj_keys)}\n"
                f"Object attributes found in this group: {', '.join(object_present) or 'None'}"
            )

            recommendation = MethodRecommendation(
                activity_name=activity.name,
                activity_action=action,
                activity_object=obj,
                events=event_indices,
                execution_environment=context,
                pattern=pattern,
                method=method,
                method_category=pattern.category if pattern else None,
                confidence=final_conf,
                confidence_explanation=confidence_explanation,
                context_attributes_used=context_present,
                context_switch=context_switch,
                context_switch_from=context_switch_from,
                context_switch_to=context_switch_to,
            )
            recommendations.append(recommendation)

        # Add implicit recommendations per recommendation approach:
        # - Switch Context on environment transitions
        # - Find Element prerequisite for Read/Write/Focus/Activate
        implicit_recommendations = matcher.create_implicit_recommendations(
            mappings, context_sequence
        )
        recommendations.extend(implicit_recommendations)

        # Priority order:
        # 1) content-level > 2) accessibility-level > 3) visual/hardware
        def _method_priority(method_name: str) -> int:
            if not method_name:
                return 999
            m = method_name.lower()
            if "dom" in m or "content" in m or "api" in m:
                return 1
            if "uia" in m or "automation" in m or "accessibility" in m:
                return 2
            if "visual" in m or "hardware" in m or "screen" in m:
                return 3
            return 10

        recommendations.sort(key=lambda r: (_method_priority(r.method), -r.confidence))

        session_id = f"{filename}:{uuid.uuid4()}"
        try:
            dfg_payload = build_dfg_payload(mappings, session_id=session_id)
        except Exception as dfg_error:
            return (
                jsonify(
                    {
                        "error": "DFG generation failed",
                        "details": str(dfg_error),
                    }
                ),
                500,
            )

        recommendation_payload = [r.to_dict() for r in recommendations]
        enriched_activities = getattr(mapper, "enriched_activities", None)
        progressive_artifacts, progressive_logic = _build_progressive_contract(
            mappings, activities, recommendation_payload, enriched_activities=enriched_activities
        )

        history_entry = {
            "id": str(uuid.uuid4()),
            "timestamp": datetime.now().isoformat(),
            "filename": filename,
            "activities": [a.name for a in activities],
            "recommendations": recommendation_payload,
            "dfg": dfg_payload,
            "progressive_artifacts": progressive_artifacts,
            "progressive_logic": progressive_logic,
            "event_column": event_column or loader.detected_column,
            "log_columns": log_columns,
            "log_preview": log_preview,
        }

        history = get_history()
        history.insert(0, history_entry)
        history = history[:MAX_HISTORY_ENTRIES]
        save_history(history)

        return jsonify(
            {
                "activities": [
                    {
                        "name": a.name,
                        "confidence": a.confidence,
                        "evidence": a.evidence,
                        "source_events": a.source_events,
                    }
                    for a in activities
                ],
                "recommendations": [r.to_dict() for r in recommendations],
                "history_id": history_entry["id"],
                "dfg": dfg_payload,
                "progressive_artifacts": progressive_artifacts,
                "progressive_logic": progressive_logic,
            }
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if os.path.exists(filepath):
            os.remove(filepath)
        session.pop("uploaded_file", None)
        session.pop("filename", None)


@app.route("/analyzing")
def analyzing():
    """Intermediate loading page with progress bar."""
    event_column = request.args.get("event_column", "")
    return render_template("analyzing.html", event_column=event_column)


@app.route("/results/<history_id>")
def results(history_id):
    history = get_history()
    entry = next((h for h in history if h["id"] == history_id), None)

    if entry is None:
        return "Analysis not found", 404

    # Backward-compatible normalization for older history entries.
    if "log_columns" not in entry or not entry.get("log_columns"):
        preview = entry.get("log_preview", [])
        if preview and isinstance(preview[0], dict):
            first = preview[0]
            if "values" in first and isinstance(first["values"], dict):
                entry["log_columns"] = list(first["values"].keys())
            else:
                # Legacy shape used event/attributes only.
                entry["log_columns"] = ["event", "attributes"]
                normalized = []
                for i, row in enumerate(preview):
                    normalized.append(
                        {
                            "row_index": row.get("row_index", i),
                            "values": {
                                "event": row.get("event", ""),
                                "attributes": row.get("attributes", {}),
                            },
                        }
                    )
                entry["log_preview"] = normalized

    return render_template("results.html", entry=entry)


@app.route("/workspace/<history_id>")
def workspace(history_id):
    history = get_history()
    entry = next((h for h in history if h["id"] == history_id), None)

    if entry is None:
        return "Analysis not found", 404

    if "progressive_artifacts" not in entry:
        entry["progressive_artifacts"] = {
            stage: {}
            for stage in PROGRESSIVE_STAGE_KEYS
        }
    if "progressive_logic" not in entry:
        entry["progressive_logic"] = {
            stage: ""
            for stage in PROGRESSIVE_STAGE_KEYS
        }

    # Enforce deterministic stage ordering for workspace replay.
    entry["progressive_artifacts"] = {
        stage: entry["progressive_artifacts"].get(stage, {})
        for stage in PROGRESSIVE_STAGE_KEYS
    }
    entry["progressive_logic"] = {
        stage: entry["progressive_logic"].get(stage, "")
        for stage in PROGRESSIVE_STAGE_KEYS
    }

    # Preserve log columns and preview for workspace table rendering.
    if "log_columns" not in entry or not entry.get("log_columns"):
        preview = entry.get("log_preview", [])
        if preview and isinstance(preview[0], dict):
            first = preview[0]
            if "values" in first and isinstance(first["values"], dict):
                entry["log_columns"] = list(first["values"].keys())
            else:
                entry["log_columns"] = ["event", "attributes"]

    return render_template("workspace.html", entry=entry)


@app.route("/history")
def history():
    history_list = get_history()
    return render_template("history.html", history=history_list)


@app.route("/history/<history_id>")
def history_detail(history_id):
    history = get_history()
    entry = next((h for h in history if h["id"] == history_id), None)

    if entry is None:
        return "Analysis not found", 404

    if "log_columns" not in entry or not entry.get("log_columns"):
        preview = entry.get("log_preview", [])
        if preview and isinstance(preview[0], dict):
            first = preview[0]
            if "values" in first and isinstance(first["values"], dict):
                entry["log_columns"] = list(first["values"].keys())
            else:
                entry["log_columns"] = ["event", "attributes"]
                normalized = []
                for i, row in enumerate(preview):
                    normalized.append(
                        {
                            "row_index": row.get("row_index", i),
                            "values": {
                                "event": row.get("event", ""),
                                "attributes": row.get("attributes", {}),
                            },
                        }
                    )
                entry["log_preview"] = normalized

    return render_template("results.html", entry=entry)


@app.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        existing = get_llm_config()
        submitted_api_key = (request.form.get("api_key", "") or "").strip()
        if not submitted_api_key or _is_masked_api_key(submitted_api_key):
            api_key = existing.get("api_key", "")
        else:
            api_key = submitted_api_key

        config = {
            "provider": request.form.get("provider", "puter"),
            "endpoint": request.form.get("endpoint", ""),
            "api_key": api_key,
            "model": request.form.get("model", "gpt-4o-mini"),
        }
        save_llm_config(config)
        return redirect(url_for("settings"))

    config = _sanitize_config_for_view(get_llm_config())
    return render_template("settings.html", config=config)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
