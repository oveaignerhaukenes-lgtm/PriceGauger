from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_chart_interaction_component_highlights_hover_and_replaces_large_popup() -> None:
    source = (ROOT / "trading_desk_legend_hover_v1.py").read_text(encoding="utf-8")

    assert "pointerover" in source
    assert "pointerout" in source
    assert "plotly_hover" in source
    assert "plotly_unhover" in source
    assert "plotly_click" in source
    assert "window.Plotly" in source
    assert "Math.min(0.12, value)" in source
    assert "pg-chart-inspector" in source
    assert "pg-chart-click-info" not in source
    assert "hideHoverPopup" in source
    assert "maximumFractionDigits" in source


def test_cursor_inspector_lives_under_legend_and_follows_nearest_time() -> None:
    source = (ROOT / "trading_desk_legend_hover_v1.py").read_text(encoding="utf-8")

    assert "function positionInspector" in source
    assert "legend.getBoundingClientRect()" in source
    assert "legendRect.bottom - rect.top + 8" in source
    assert "function nearestAnchor" in source
    assert "function nearestIndex" in source
    assert "renderInspectorsAtX(xValue)" in source
    assert "O ${formatNumber(trace.open?.[index])}" in source
    assert "isPnl ? '%' : ''" in source


def test_browser_local_view_registry_prevents_pan_zoom_snap_back() -> None:
    source = (ROOT / "trading_desk_legend_hover_v1.py").read_text(encoding="utf-8")

    assert "window.__pricegaugerPlotlyViews" in source
    assert "function isNavigationRelayout" in source
    assert "snapshotBrowserView(graph)" in source
    assert "applyBrowserView(graph, state)" in source
    assert "graph.on?.('plotly_relayout', onRelayout)" in source
    assert "graph.on?.('plotly_doubleclick', onDoubleClick)" in source
    assert "viewRegistry.delete(key)" in source
    assert "state.restoringView" in source


def test_live_chart_trackpad_contract_is_x_zoom_x_pan_and_price_y_scale() -> None:
    source = (ROOT / "trading_desk_legend_hover_v1.py").read_text(encoding="utf-8")

    assert "event.ctrlKey || event.metaKey" in source
    assert "graph._context.scrollZoom = false" in source
    assert "'xaxis.range'" in source
    assert "Math.abs(gesture.dx) > Math.abs(gesture.dy)" in source
    assert "'yaxis.range'" in source
    assert "event.preventDefault()" in source
    assert "capture: true" in source


def test_strategy_chart_is_discovered_by_same_interaction_component() -> None:
    source = (ROOT / "trading_desk_legend_hover_v1.py").read_text(encoding="utf-8")
    assert "AutoManagerPnlProduct:" in source
    assert "legend.maxheight" in source
    assert "Legend · hover / scroll" in source
    assert "renderInspectorsAtX" in source


def test_interaction_component_is_rendered_with_stable_chart_controls() -> None:
    source = (ROOT / "pages" / "0_TradingDesk.py").read_text(encoding="utf-8")
    controls = source.split("def _render_live_chart_controls() -> None:", 1)[1].split(
        "def _live_chart_uirevision()", 1
    )[0]
    live_chart = source.split("def _render_live_chart() -> None:", 1)[1].split(
        "def _render_automanager_workspace()", 1
    )[0]

    assert "render_trading_desk_legend_hover_v1" in controls
    assert "render_trading_desk_legend_hover_v1" not in live_chart
