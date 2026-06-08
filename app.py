"""Flask web application for RPA UI Log Analyzer."""

import logging
import os
import json
import secrets
import threading
import time
import uuid
import csv
import warnings
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from werkzeug.utils import secure_filename

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Keep the root logger at INFO so third-party libraries (urllib3, matplotlib,
# graphviz, pm4py) don't flood the console, but keep this app's own loggers
# verbose for debugging the pipeline.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger("src").setLevel(logging.DEBUG)
logging.getLogger(__name__).setLevel(logging.DEBUG)
_logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "data/uploads"
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
app.config["JSON_SORT_KEYS"] = False
app.json.sort_keys = False

_secret_key = os.environ.get("SECRET_KEY")
if not _secret_key:
    _secret_key = secrets.token_hex(32)
    warnings.warn(
        "SECRET_KEY environment variable is not set. Sessions will not persist across "
        "server restarts. Set SECRET_KEY for production deployments.",
        RuntimeWarning,
        stacklevel=1,
    )
app.config["SECRET_KEY"] = _secret_key

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs("config", exist_ok=True)
os.makedirs("data", exist_ok=True)
os.makedirs("skills", exist_ok=True)
os.makedirs(os.path.join("data", "progressive"), exist_ok=True)

from src.web.progressive import bp as _progressive_bp
app.register_blueprint(_progressive_bp)

DEFAULT_LLM_CONFIG = {
    "provider": "puter",
    "endpoint": "",
    "api_key": "",
    "model": "gpt-4o-mini",
}

MAX_PREVIEW_ROWS = 100
MAX_HISTORY_ENTRIES = 200
MAX_UPLOAD_MB = 16
LLM_DETECT_SAMPLE_ROWS = 100

# In-memory progress store keyed by analysis_id (one entry per active analysis).
_analysis_progress: dict = {}
_progress_lock = threading.Lock()
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


def _read_csv_dedup(filepath: str, max_rows: int | None = None) -> tuple:
    """Open a CSV and return (unique_fieldnames, rows_as_dicts).

    Uses utf-8-sig to strip an optional BOM and CSVLoader._dedup_headers so that
    files with duplicate column names are read correctly.
    """
    from src.parser.csv_loader import CSVLoader
    with open(filepath, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        raw_headers = next(reader, [])
        headers = CSVLoader._dedup_headers(raw_headers)
        rows = []
        for i, values in enumerate(reader):
            if max_rows is not None and i >= max_rows:
                break
            rows.append({h: (values[j] if j < len(values) else "") for j, h in enumerate(headers)})
    return headers, rows


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


def _get_csrf_token() -> str:
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)
    return session["csrf_token"]


def _validate_csrf(form_token: str) -> bool:
    return bool(form_token) and secrets.compare_digest(
        form_token, session.get("csrf_token", "")
    )


def get_llm_config():
    config_path = "config/llm_config.json"
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            return json.load(f)
    return DEFAULT_LLM_CONFIG.copy()


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


def _load_full_log(entry: dict) -> list:
    """Return full CSV rows for the entry, falling back to the stored preview."""
    filename = entry.get("filename", "")
    if filename:
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        if os.path.exists(filepath):
            try:
                _, rows = _read_csv_dedup(filepath)
                return [{"row_index": i, "values": _redact_row(row)} for i, row in enumerate(rows)]
            except OSError:
                pass
    return entry.get("log_preview", [])


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
            columns, rows = _read_csv_dedup(filepath, max_rows=MAX_PREVIEW_ROWS)

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
                llm_recommended=loader.llm_recommended,
                rows=rows,
                filename=filename,
            )

        except Exception:
            _logger.exception("Error during column detection in /select-column")
            return jsonify({"error": "An internal error occurred. Please try again."}), 500

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
        columns, preview_rows = _read_csv_dedup(filepath, max_rows=LLM_DETECT_SAMPLE_ROWS)

        from src.llm.client import get_llm_client
        from src.parser.csv_loader import CSVLoader

        llm_client = get_llm_client()
        loader = CSVLoader(llm_client)
        detected = loader._detect_event_column_with_llm(
            columns, sample_rows=preview_rows
        )

        session["uploaded_file"] = filepath
        session["filename"] = filename

        return jsonify(
            {
                "columns": columns,
                "detected_column": detected,
                "llm_recommended": loader.llm_recommended,
                "upload_id": str(uuid.uuid4()),
            }
        )

    except Exception:
        _logger.exception("Error during column detection in /detect-column")
        return jsonify({"error": "An internal error occurred. Please try again."}), 500


@app.route("/progress", methods=["GET"])
def progress():
    analysis_id = session.get("analysis_id")
    if not analysis_id:
        return jsonify({"stage": "waiting", "completed": 0, "total": 0})
    with _progress_lock:
        state = dict(_analysis_progress.get(analysis_id, {"stage": "waiting", "completed": 0, "total": 0}))
    return jsonify(state)


def _synthesize_recommendations_from_progressive(entry):
    """Populate entry.recommendations from progressive_artifacts when it's empty."""
    if entry.get("recommendations"):
        return
    mr_recs = (
        entry.get("progressive_artifacts", {})
        .get("method_recommendation", {})
        .get("recommendations", [])
    )
    if not mr_recs:
        return
    entry["recommendations"] = [
        {
            "inferred_activity": r.get("inferred_activity", ""),
            "activity_action": r.get("activity_action", ""),
            "activity_object": r.get("activity_object", ""),
            "events": r.get("events", []),
            "execution_environment": r.get("execution_environment", ""),
            "pattern_matched": r.get("pattern_matched"),
            "method": r.get("method") or r.get("recommended_method"),
            "method_category": r.get("method_category"),
            "confidence": r.get("confidence", 0),
            "confidence_explanation": None,
            "context_attributes_used": None,
            "context_switch": r.get("context_switch", False),
            "context_switch_from": None,
            "context_switch_to": None,
            "inference_evidence": [],
            "inference_reasoning": "",
        }
        for r in mr_recs
    ]


@app.route("/results/<history_id>")
def results(history_id):
    history = get_history()
    entry = next((h for h in history if h["id"] == history_id), None)

    if entry is None:
        return "Analysis not found", 404

    _synthesize_recommendations_from_progressive(entry)

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

    entry["log_preview"] = _load_full_log(entry)
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

    _synthesize_recommendations_from_progressive(entry)

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

    entry["log_preview"] = _load_full_log(entry)
    return render_template("results.html", entry=entry)


@app.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        if not _validate_csrf(request.form.get("csrf_token", "")):
            _logger.warning("CSRF validation failed for POST /settings")
            return "Forbidden", 403

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
    return render_template("settings.html", config=config, csrf_token=_get_csrf_token())


if __name__ == "__main__":
    app.run(debug=True, port=5001)
