"""Tests for welcome-first routing and upload flow compatibility."""

import app as webapp


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
