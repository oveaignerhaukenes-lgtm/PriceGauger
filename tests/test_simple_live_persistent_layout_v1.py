from pathlib import Path

SOURCE = Path("tradingdesk_ui/charts/lightweight/simple_live_v2.py").read_text()


def test_live_chart_layout_is_browser_persistent_and_scoped_to_chart():
    assert "'pg:tradingdesk:chart-layout:v1:' + chartId" in SOURCE
    assert "window.localStorage.setItem(layoutKey" in SOURCE
    assert "window.localStorage.getItem(layoutKey)" in SOURCE
    assert "parentElement.style.resize = 'vertical'" in SOURCE
    assert "parentElement.style.border = '1px solid ' + theme.border" in SOURCE


def test_live_chart_refresh_preserves_manual_size_and_pane_ratios():
    assert "entry.parent.style.height =" not in SOURCE
    assert "root.addEventListener('pointerup', savePaneSizes)" in SOURCE
    assert "root.addEventListener('touchend', savePaneSizes" in SOURCE
    assert "pane?.setStretchFactor?.(Number(savedPaneShares[index]))" in SOURCE
    assert "entry.resizeObserver?.disconnect()" in SOURCE
