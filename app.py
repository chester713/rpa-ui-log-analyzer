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
            detected = loader._detect_event_column_with_llm(columns)

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

    return redirect("/")


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
        detected = loader._detect_event_column_with_llm(columns)

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
        activities = [m.activity for m in mappings]

        from src.matching.pattern_matcher import get_context_from_events, PatternMatcher
        from src.matching import PATTERNS
        from src.models.pattern import MethodRecommendation
        from src.process_mining import build_dfg_payload

        recommendations = []
        matcher = PatternMatcher(PATTERNS)
        context_sequence = []
        inference_rules = get_inference_rules().get("rules", [])

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

            # Apply configurable grouped-event inference rules.
            event_text = " ".join([e.event.lower() for e in events_list])
            for rule in inference_rules:
                if not rule.get("enabled", True):
                    continue
                match = rule.get("match", {})
                all_keys = match.get("all_event_keywords", [])
                any_keys = match.get("any_event_keywords", [])

                all_ok = all(k in event_text for k in all_keys) if all_keys else True
                any_ok = any(k in event_text for k in any_keys) if any_keys else True

                if all_ok and any_ok:
                    is_web_group = any(
                        (e.attributes.get("browser_url") or e.attributes.get("url"))
                        or str(e.attributes.get("application", "")).lower()
                        in ["edge", "chrome", "firefox", "safari"]
                        or str(e.attributes.get("category", "")).lower() == "browser"
                        for e in events_list
                    )
                    output = rule.get("output", {})
                    activity.name = (
                        output.get("web_activity_name", activity.name)
                        if is_web_group
                        else output.get("non_web_activity_name", activity.name)
                    )
                    activity.confidence = max(
                        activity.confidence, float(output.get("min_confidence", 0.0))
                    )

            # Ensure rule-based overrides still pass through naming enrichment,
            # so generic labels like "Write HTML element on webpage" become
            # specific Action + Target + Context names.
            if hasattr(inferrer, "_post_process_inferred_name"):
                activity.name = inferrer._post_process_inferred_name(
                    activity.name, events_list
                )

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

            action, obj = (
                activity.name.split(None, 1)
                if " " in activity.name
                else (activity.name, "")
            )

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

        history_entry = {
            "id": str(uuid.uuid4()),
            "timestamp": datetime.now().isoformat(),
            "filename": filename,
            "activities": [a.name for a in activities],
            "recommendations": [r.to_dict() for r in recommendations],
            "dfg": dfg_payload,
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
