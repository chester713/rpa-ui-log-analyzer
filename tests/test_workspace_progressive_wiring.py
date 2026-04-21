"""Tests for welcome-first routing and upload flow compatibility."""

from pathlib import Path

import app as webapp


REQUIRED_STAGES = [
    "event_grouping",
    "activity_naming",
    "action_object_extraction",
    "pattern_matching",
    "context_determination",
    "method_recommendation",
]

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"


def _template_text(name: str) -> str:
    return (TEMPLATE_DIR / name).read_text(encoding="utf-8")


def _history_entry() -> dict:
    artifacts = {stage: {"items": []} for stage in REQUIRED_STAGES}
    logic = {stage: f"logic for {stage}" for stage in REQUIRED_STAGES}
    return {
        "id": "history-123",
        "timestamp": "2026-04-21T00:00:00",
        "filename": "sample.csv",
        "activities": ["Open App", "Click Submit"],
        "recommendations": [],
        "dfg": {
            "nodes": ["Open App", "Click Submit"],
            "edges": [{"source": "Open App", "target": "Click Submit", "frequency": 1}],
            "start_activities": {"Open App": 1},
            "end_activities": {"Click Submit": 1},
        },
        "event_column": "Event",
        "log_columns": ["Event", "application"],
        "log_preview": [
            {"row_index": 0, "values": {"Event": "Open app", "application": "chrome"}}
        ],
        "progressive_artifacts": artifacts,
        "progressive_logic": logic,
    }


def test_root_renders_welcome_page_with_continue_action() -> None:
    client = webapp.app.test_client()

    response = client.get("/")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Welcome" in html
    assert "href=\"/upload\"" in html


def test_upload_route_renders_existing_upload_form_actions() -> None:
    client = webapp.app.test_client()

    response = client.get("/upload")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "id=\"uploadForm\"" in html
    assert "action=\"/select-column\"" in html
    assert "data-detect-column-url=\"/detect-column\"" in html


def test_upload_and_column_selection_routes_remain_available() -> None:
    routes = {str(rule) for rule in webapp.app.url_map.iter_rules()}

    assert "/select-column" in routes
    assert "/detect-column" in routes


def test_workspace_route_loads_history_and_passes_progressive_contract(monkeypatch) -> None:
    entry = _history_entry()
    monkeypatch.setattr(webapp, "get_history", lambda: [entry])

    client = webapp.app.test_client()
    response = client.get(f"/workspace/{entry['id']}")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    for stage in REQUIRED_STAGES:
        assert stage in html


def test_workspace_route_returns_404_for_unknown_history_id(monkeypatch) -> None:
    monkeypatch.setattr(webapp, "get_history", lambda: [_history_entry()])
    client = webapp.app.test_client()

    response = client.get("/workspace/does-not-exist")

    assert response.status_code == 404


def test_workspace_template_contains_six_progressive_sections_and_logic_areas() -> None:
    template = _template_text("workspace.html")

    for stage in REQUIRED_STAGES:
        assert f'data-stage-key="{stage}"' in template
    assert "const progressiveArtifacts = {{ entry.progressive_artifacts | tojson }};" in template
    assert "const progressiveLogic = {{ entry.progressive_logic | tojson }};" in template
    assert "textContent" in template


def test_results_template_still_keeps_export_and_dfg_wiring() -> None:
    template = _template_text("results.html")

    assert "const dfg = {{ entry.dfg | tojson }};" in template
    assert "document.getElementById('exportBtn').addEventListener('click'" in template
