"""UI contract for the bundled default LLM and the results page details.

The prototype ships a default hosted LLM, so the UI offers no way to choose a
model or supply a key, and every LLM-derived value shown to the user comes from
the activity-naming output (the same data the CLI prints with --verbose).
"""

import re
from pathlib import Path

import app as webapp

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"


def _template_text(name: str) -> str:
    return (TEMPLATE_DIR / name).read_text(encoding="utf-8")


def test_settings_page_has_been_removed() -> None:
    client = webapp.app.test_client()

    assert client.get("/settings").status_code == 404
    assert not (TEMPLATE_DIR / "settings.html").exists()
    for template in TEMPLATE_DIR.glob("*.html"):
        assert "/settings" not in template.read_text(encoding="utf-8"), template.name


def test_column_selection_page_has_no_heuristic_fallback_ui() -> None:
    template = _template_text("columns.html").lower()

    assert "heuristic" not in template


def test_welcome_page_labels_steps_3_and_4_as_lookups_not_llm() -> None:
    html = _template_text("welcome.html")

    def badge_after(title: str) -> str:
        match = re.search(rf'{re.escape(title)}</span>\s*<span class="badge ([^"]+)">', html)
        assert match, f"badge for {title!r} not found"
        return match.group(1)

    assert badge_after("Event Grouping") == "badge-rule"
    assert badge_after("Activity Naming") == "badge-llm"
    assert badge_after("Action / Object Extraction") == "badge-lookup"
    assert badge_after("Pattern Matching") == "badge-lookup"
    assert badge_after("Context Identification") == "badge-rule"


def test_results_template_shows_llm_confidence_and_evidence() -> None:
    template = _template_text("results.html")

    assert 'id="dConfidence"' in template
    assert 'id="dEvidence"' in template
    assert "function renderConfidenceEvidence(namingEntry, rec)" in template
    # Details come from the activity-naming artifact, matched by activity name.
    assert "progressiveArtifacts?.activity_naming?.activities" in template
    assert "renderConfidenceEvidence(namingEntry || null, rec);" in template
    # LLM text is inserted as text, never as HTML.
    assert "row.textContent = '• ' + String(text);" in template


def test_results_route_embeds_confidence_and_evidence_from_activity_naming(monkeypatch) -> None:
    entry = {
        "id": "h1",
        "timestamp": "2026-10-08T00:00:00",
        "filename": "does-not-exist.csv",
        "event_column": "event",
        "log_columns": ["event"],
        "log_preview": [{"row_index": 0, "values": {"event": "click"}}],
        "recommendations": [
            {
                "inferred_activity": "Activate Submit button",
                "events": [0],
                "execution_environment": "web",
                "pattern_matched": "Activate",
                "method": "HTML DOM manipulation",
                "confidence": 0.9,
            }
        ],
        "dfg": {"nodes": [], "edges": [], "start_activities": {}, "end_activities": {}},
        "progressive_artifacts": {
            "activity_naming": {
                "activities": [
                    {
                        "activity_name": "Activate Submit button",
                        "activity_type": "main",
                        "is_implicit": False,
                        "confidence": 0.9,
                        "evidence": ["button element with id submit"],
                    }
                ]
            }
        },
    }
    monkeypatch.setattr(webapp, "get_history", lambda: [entry])

    response = webapp.app.test_client().get("/results/h1")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "button element with id submit" in html
    assert 'id="dConfidence"' in html
