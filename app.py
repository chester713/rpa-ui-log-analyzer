"""Flask web application for RPA UI Log Analyzer."""

import os
import json
import uuid
import csv
import tempfile
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "data/uploads"
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")

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


def get_llm_config():
    config_path = "config/llm_config.json"
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            return json.load(f)
    return DEFAULT_LLM_CONFIG.copy()


def save_llm_config(config):
    config_path = "config/llm_config.json"
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)


def get_history():
    history_path = "data/history.json"
    if os.path.exists(history_path):
        with open(history_path, "r") as f:
            return json.load(f)
    return []


def save_history(history):
    history_path = "data/history.json"
    with open(history_path, "w") as f:
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
                    if i < 100:  # Preview first 100 rows
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

        recommendations = []
        matcher = PatternMatcher(PATTERNS)

        for mapping in mappings:
            activity = mapping.activity
            events_list = mapping.events
            context = get_context_from_events(events_list)

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

            recommendation = MethodRecommendation(
                activity_name=activity.name,
                activity_action=action,
                activity_object=obj,
                events=event_indices,
                execution_environment=context,
                pattern=pattern,
                method=method,
                method_category=pattern.category if pattern else None,
                confidence=activity.confidence,
                context_switch=context_switch,
                context_switch_from=context_switch_from,
                context_switch_to=context_switch_to,
            )
            recommendations.append(recommendation)

        history_entry = {
            "id": str(uuid.uuid4()),
            "timestamp": datetime.now().isoformat(),
            "filename": filename,
            "activities": [a.name for a in activities],
            "recommendations": [r.to_dict() for r in recommendations],
        }

        history = get_history()
        history.insert(0, history_entry)
        save_history(history)

        return jsonify(
            {
                "activities": [a.to_dict() for a in activities],
                "recommendations": [r.to_dict() for r in recommendations],
                "history_id": history_entry["id"],
            }
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if os.path.exists(filepath):
            os.remove(filepath)
        session.pop("uploaded_file", None)
        session.pop("filename", None)


@app.route("/results/<history_id>")
def results(history_id):
    history = get_history()
    entry = next((h for h in history if h["id"] == history_id), None)

    if entry is None:
        return "Analysis not found", 404

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

    return render_template("results.html", entry=entry)


@app.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        config = {
            "provider": request.form.get("provider", "puter"),
            "endpoint": request.form.get("endpoint", ""),
            "api_key": request.form.get("api_key", ""),
            "model": request.form.get("model", "gpt-4o-mini"),
        }
        save_llm_config(config)
        return redirect(url_for("settings"))

    config = get_llm_config()
    return render_template("settings.html", config=config)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
