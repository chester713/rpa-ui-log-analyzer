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


def test_results_template_wires_node_click_to_event_row_highlight() -> None:
    template = _template_text()

    assert "function findRowsForActivity(activityName)" in template
    assert "tr.classList.add('row-related')" in template
    assert "tr.classList.remove('row-active', 'row-related')" in template
    assert "circle.addEventListener('click', () => activateDfgNode(" in template


def test_results_template_wires_event_row_click_to_node_highlight() -> None:
    template = _template_text()

    assert "function activateDfgNode(activityName, opts = {})" in template
    assert "node.classList.add('dfg-node-active')" in template
    assert "const activityName = rec?.inferred_activity || null;" in template
    assert "if (activityName) activateDfgNode(activityName);" in template


def test_results_template_keeps_single_active_focus_state() -> None:
    template = _template_text()

    assert "let activeDfgActivity = null;" in template
    assert "if (activeDfgActivity === activityKey && !opts.force)" in template
    assert "node.classList.remove('dfg-node-active', 'dfg-node-related')" in template
    assert "node.classList.add(isActive ? 'dfg-node-active' : 'dfg-node-related')" in template
