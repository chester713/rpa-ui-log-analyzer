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

    # A DFG node click routes through the cross-panel coordinator, which
    # highlights the matching recommendation's log rows and detail panel.
    assert "function activateDfgNode(activityName)" in template
    assert "function findRecommendationByActivity(activityName)" in template
    assert "function applyRowHighlights(" in template
    assert "circle.addEventListener('click', () => {" in template
    assert "selectActivity(actIdx, activityKey, { source: 'dfg' });" in template
    assert "renderDetails(rec);" in template


def test_results_template_wires_event_row_click_to_node_highlight() -> None:
    template = _template_text()

    # A log-row click selects the matching activity and syncs the DFG node.
    assert "function activateDfgNode(activityName)" in template
    assert "node.classList.add('dfg-node-active')" in template
    assert "document.querySelectorAll('tr.row-clickable').forEach(tr => {" in template
    assert "selectActivity(actIdx, activityName, { source: 'log', activeLogRow: idx });" in template
    assert "if (activityName) activateDfgNode(activityName);" in template


def test_results_template_keeps_single_active_focus_state() -> None:
    template = _template_text()

    assert "let activeDfgActivity = null;" in template
    assert "activeDfgActivity = activityKey;" in template
    assert "node.classList.remove('dfg-node-active', 'dfg-node-related')" in template
    assert "node.classList.add('dfg-node-active')" in template


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
