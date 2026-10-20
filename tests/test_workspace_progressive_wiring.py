"""Routing: welcome page, upload flow, and the workspace for analyses of earlier versions."""

from pathlib import Path

import app as webapp


TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"


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


def test_workspace_route_returns_404_for_unknown_history_id(monkeypatch) -> None:
    monkeypatch.setattr(webapp, "get_history", lambda: [])

    assert webapp.app.test_client().get("/workspace/missing").status_code == 404
    assert webapp.app.test_client().get("/results/missing").status_code == 404


def test_analysis_of_an_earlier_version_asks_to_rerun(monkeypatch) -> None:
    entry = {"id": "old", "timestamp": "2026-04-21T00:00:00", "filename": "sample.csv",
             "progressive_artifacts": {"event_grouping": {"groups": []}}}
    monkeypatch.setattr(webapp, "get_history", lambda: [entry])
    client = webapp.app.test_client()

    for url in ("/workspace/old", "/results/old"):
        response = client.get(url)
        assert response.status_code == 200
        assert "earlier version of the prototype" in response.get_data(as_text=True)


def test_history_detail_redirects_to_results() -> None:
    response = webapp.app.test_client().get("/history/abc")

    assert response.status_code in (301, 302)
    assert response.headers["Location"].endswith("/results/abc")
