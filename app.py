"""Flask web application for RPA UI Log Analyzer."""

import os
import json
import uuid
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for
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


@app.route("/analyze", methods=["POST"])
def analyze():
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
        result = analyze_csv(filepath)

        history_entry = {
            "id": str(uuid.uuid4()),
            "timestamp": datetime.now().isoformat(),
            "filename": filename,
            "activities": [a.name for a in result.activities],
            "recommendations": [r.to_dict() for r in result.recommendations],
        }

        history = get_history()
        history.insert(0, history_entry)
        save_history(history)

        return jsonify(
            {
                "activities": [a.to_dict() for a in result.activities],
                "recommendations": [r.to_dict() for r in result.recommendations],
                "history_id": history_entry["id"],
            }
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if os.path.exists(filepath):
            os.remove(filepath)


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
