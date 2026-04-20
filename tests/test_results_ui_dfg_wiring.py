"""Template-level tests for DFG rendering and wiring in results UI."""

from pathlib import Path


TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "templates" / "results.html"


def _template_text() -> str:
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def test_results_template_contains_full_width_dfg_section() -> None:
    template = _template_text()

    assert '<section id="dfgSection" class="dfg-section">' in template
    assert "const dfg = {{ entry.dfg | tojson }};" in template
    assert "<svg id=\"dfgSvg\"" in template
    assert ".dfg-section {" in template
    assert "width: 100%;" in template
