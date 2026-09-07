from __future__ import annotations

from pathlib import Path

from tradingdesk_ui.charts.lightweight.pnl_strategy_lab_desktop_v4 import _STRATEGY_LAB_DESKTOP_JS


ROOT = Path(__file__).resolve().parents[1]


def test_strategy_lab_baseline_restores_shared_relative_return_pane() -> None:
    rendered = _STRATEGY_LAB_DESKTOP_JS

    assert "for (const model of Array.from(payload.baseline_models || []))" in rendered
    assert "live = chart.addSeries" in rendered
    assert "const carrier = chart.addSeries" in rendered
    assert rendered.count("}, 0);") >= 4


def test_strategy_lab_mobile_pinch_is_reserved_for_native_chart_scaling() -> None:
    rendered = _STRATEGY_LAB_DESKTOP_JS

    assert "touchAction: 'pan-y'" in rendered
    assert "event.touches?.length >= 2" in rendered
    assert "event.preventDefault()" in rendered
    assert "passive: false" in rendered
    assert "pinch: true" in rendered


def test_strategy_lab_navigation_can_expand_beyond_short_real_history() -> None:
    rendered = _STRATEGY_LAB_DESKTOP_JS

    assert "const navigationStart = navigationEnd - (3 * 86400);" in rendered
    assert "const navigationCarrier = chart.addSeries" in rendered
    assert "navigationCarrier.setData([{ time: navigationStart }, { time: navigationEnd }]);" in rendered
    nav_start = rendered.index("const navigationCarrier = chart.addSeries")
    nav_end = rendered.index("navigationCarrier.setData", nav_start)
    navigation_block = rendered[nav_start:nav_end]
    assert "color: 'rgba(0,0,0,0)'" in navigation_block
    assert "visible: false" not in navigation_block
    assert "navigationEnd - (4 * 3600)" in rendered
    assert "['12t', 12 * 3600]" in rendered
    assert "['1d', 86400]" in rendered
    assert "['3d', 3 * 86400]" in rendered


def test_strategy_lab_supports_total_and_window_relative_regime_views() -> None:
    rendered = _STRATEGY_LAB_DESKTOP_JS

    assert "totalButton.textContent = 'Total'" in rendered
    assert "relativeButton.textContent = 'Relativ'" in rendered
    assert "comparisonView = desktopLayout ? 'relative' : 'total'" in rendered
    assert "function baselineValue(points, from)" in rendered
    assert "value: value - baseline" in rendered
    assert "subscribeVisibleTimeRangeChange" in rendered
    assert "if (comparisonView === 'relative') applyComparisonView(range)" in rendered
    assert "comparableSeries.push({ api: market" in rendered
    assert "comparableSeries.push({ api: live" in rendered
    assert "comparableSeries.push({ api, data: modelData" in rendered


def test_strategy_lab_desktop_places_legend_in_header_without_changing_mobile() -> None:
    rendered = _STRATEGY_LAB_DESKTOP_JS

    assert "window.matchMedia('(min-width: 900px)').matches" in rendered
    assert "headerRow.append(headerInfo, legend)" in rendered
    assert "shell.insertBefore(headerRow, toolbar)" in rendered
    assert "if (desktopLayout)" in rendered
    assert "maxWidth: '62vw'" in rendered


def test_strategy_lab_desktop_uses_stacked_event_annotations() -> None:
    rendered = _STRATEGY_LAB_DESKTOP_JS

    assert "function renderDesktopEventAnnotations()" in rendered
    assert "const laneLastX = []" in rendered
    assert "while (lane < laneLastX.length" in rendered
    assert "desktopEventCarrier.priceToCoordinate" in rendered
    assert "chart.timeScale().timeToCoordinate" in rendered
    assert "borderLeft: `1px solid ${color}`" in rendered
    assert "desktopLiveEvents = rawLiveEvents" in rendered
    assert "rawLiveEvents.map((item) => ({ ...item, label: '' }))" in rendered
    assert "scheduleDesktopEventAnnotations()" in rendered


def test_tradingdesk_mounts_desktop_strategy_lab_without_execution_changes() -> None:
    source = (ROOT / "tradingdesk_automanage_panel_v2.py").read_text(encoding="utf-8")

    assert "pnl_strategy_lab_desktop_v4" in source
    assert "render_strategy_lab_pnl_v4" in source
    assert "request_manual_target_v2" not in source
    assert "switch_live_strategy_v2" not in source
