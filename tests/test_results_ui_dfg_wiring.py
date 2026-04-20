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
    assert "function findRecommendationByActivity(activityName)" in template
    assert "currentRow = null;" in template
    assert "applyRowHighlights(preserveActiveRow ? currentRow : null, relatedRows);" in template
    assert "if (opts.syncDetails !== false)" in template
    assert "renderDetails(rec);" in template
    assert "tr.classList.add('row-related')" in template
    assert "tr.classList.remove('row-active', 'row-related')" in template
    assert "circle.addEventListener('click', () => activateDfgNode(" in template


def test_results_template_wires_event_row_click_to_node_highlight() -> None:
    template = _template_text()

    assert "function activateDfgNode(activityName, opts = {})" in template
    assert "node.classList.add('dfg-node-active')" in template
    assert "const activityName = rec?.inferred_activity || null;" in template
    assert "if (activityName) activateDfgNode(activityName, { preserveActiveRow: true, syncDetails: false });" in template


def test_results_template_keeps_single_active_focus_state() -> None:
    template = _template_text()

    assert "let activeDfgActivity = null;" in template
    assert "if (activeDfgActivity === activityKey && !opts.force)" in template
    assert "node.classList.remove('dfg-node-active', 'dfg-node-related')" in template
    assert "node.classList.add(isActive ? 'dfg-node-active' : 'dfg-node-related')" in template


def test_results_template_includes_dfg_zoom_controls() -> None:
    template = _template_text()

    assert 'id="dfgZoomInBtn"' in template
    assert 'id="dfgZoomOutBtn"' in template
    assert 'id="dfgResetZoomBtn"' in template
    assert 'id="dfgZoomSlider"' in template
    assert 'min="100"' in template
    assert 'max="500"' in template
    assert 'step="1"' in template
    assert "id=\"dfgZoomLevel\"" in template
    assert "function bindDfgZoomControls()" in template
    assert "function setDfgZoom(scale)" in template
    assert "const DFG_MIN_ZOOM = 1;" in template
    assert "const DFG_MAX_ZOOM = 5;" in template
    assert "zoomSlider.addEventListener('input'" in template
