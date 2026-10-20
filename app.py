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
os.makedirs(os.path.join("data", "progressive"), exist_ok=True)

from src.web.progressive import bp as _progressive_bp
app.register_blueprint(_progressive_bp)

MAX_PREVIEW_ROWS = 100
MAX_HISTORY_ENTRIES = 200
MAX_UPLOAD_MB = 16
LLM_DETECT_SAMPLE_ROWS = 100

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


def _find_entry(history_id):
    return next((h for h in get_history() if h.get("id") == history_id), None)


def _view_for(entry):
    """The stored analysis of a history entry, as shown by the workspace and results pages."""
    from src.web.progressive import build_view
    from src.web.step_store import StepStore

    aid = entry.get("progressive_aid")
    if not aid or not StepStore.exists(aid):
        return None
    return build_view(StepStore(aid))


@app.route("/results/<history_id>")
def results(history_id):
    entry = _find_entry(history_id)
    if entry is None:
        return "Analysis not found", 404
    return render_template("results.html", entry=entry, view=_view_for(entry))


@app.route("/workspace/<history_id>")
def workspace(history_id):
    from src.web.progressive import STAGES, STAGE_GROUPS, STAGE_LOGIC

    entry = _find_entry(history_id)
    if entry is None:
        return "Analysis not found", 404
    return render_template(
        "workspace.html", entry=entry, view=_view_for(entry),
        stages=STAGES, stage_groups=STAGE_GROUPS, logic=STAGE_LOGIC,
    )


@app.route("/history")
def history():
    return render_template("history.html", history=get_history())


@app.route("/history/<history_id>")
def history_detail(history_id):
    return redirect(url_for("results", history_id=history_id))


if __name__ == "__main__":
    app.run(debug=True, port=5001)
