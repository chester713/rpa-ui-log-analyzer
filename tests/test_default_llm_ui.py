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


def test_welcome_page_follows_the_seven_steps_of_the_approach() -> None:
    html = _template_text("welcome.html")

    def badge_after(title: str) -> str:
        match = re.search(rf'{re.escape(title)}</span>\s*<span class="badge ([^"]+)">', html)
        assert match, f"badge for {title!r} not found"
        return match.group(1)

    assert badge_after("Segment events by context") == "badge-rule"
    assert badge_after("Abstract higher-level UI activities") == "badge-llm"
    assert badge_after("Normalise UI activities") == "badge-llm"
    assert badge_after("Add implicit activities") == "badge-rule"
    assert badge_after("Match patterns") == "badge-lookup"
    assert badge_after("Determine environment and object type") == "badge-rule"
    assert badge_after("Recommend prioritised methods") == "badge-rule"
    assert "infer" not in html.lower()


def test_results_template_shows_llm_confidence_and_evidence_as_text() -> None:
    template = _template_text("results.html")

    assert 'id="dConfidence"' in template
    assert 'id="dEvidence"' in template
    assert "map(e => `<li>${esc(e)}</li>`)" in template  # LLM text is escaped
