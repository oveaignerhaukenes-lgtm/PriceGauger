from __future__ import annotations

from pathlib import Path

from tradingdesk_ui.charts.lightweight.pnl_strategy_lab_simple_v5 import _STRATEGY_LAB_SIMPLE_JS


ROOT = Path(__file__).resolve().parents[1]


def test_strategy_lab_baseline_keeps_shared_percentage_return_pane() -> None:
    rendered = _STRATEGY_LAB_SIMPLE_JS

    assert "for (const model of Array.from(payload.baseline_models || []))" in rendered
    assert "live = chart.addSeries" in rendered
    assert "const carrier = chart.addSeries" in rendered
    assert rendered.count("}, 0);") >= 4


def test_strategy_lab_mobile_pinch_is_reserved_for_native_chart_scaling() -> None:
    rendered = _STRATEGY_LAB_SIMPLE_JS

    assert "touchAction: 'pan-y'" in rendered
    assert "event.touches?.length >= 2" in rendered
    assert "event.preventDefault()" in rendered
    assert "passive: false" in rendered
    assert "pinch: true" in rendered


def test_strategy_lab_navigation_can_expand_beyond_short_real_history() -> None:
    rendered = _STRATEGY_LAB_SIMPLE_JS

    assert "const navigationStart = navigationEnd - (3 * 86400);" in rendered
    assert "const navigationCarrier = chart.addSeries" in rendered
    assert "navigationCarrier.setData([{ time: navigationStart }, { time: navigationEnd }]);" in rendered
    assert "navigationEnd - (4 * 3600)" in rendered
    assert "['12t', 12 * 3600]" in rendered
    assert "['1d', 86400]" in rendered
    assert "['3d', 3 * 86400]" in rendered


def test_strategy_lab_is_always_normalized_to_visible_window_start() -> None:
    rendered = _STRATEGY_LAB_SIMPLE_JS

    assert "let comparisonView = 'relative'" in rendered
    assert "function baselineValue(points, from)" in rendered
    assert "value: value - baseline" in rendered
    assert "subscribeVisibleTimeRangeChange" in rendered
    assert "applyComparisonView(range)" in rendered
    assert "totalButton.textContent" not in rendered
    assert "relativeButton.textContent" not in rendered
    assert "comparableSeries.push({ api: market" in rendered
    assert "comparableSeries.push({ api: live" in rendered
    assert "comparableSeries.push({ api, data: modelData" in rendered


def test_strategy_lab_legend_wraps_below_chart_without_private_scroll() -> None:
    rendered = _STRATEGY_LAB_SIMPLE_JS

    assert "flexWrap: 'wrap'" in rendered
    assert "overflow: 'visible'" in rendered
    assert "whiteSpace: 'normal'" in rendered
    assert "flex: '0 1 auto'" in rendered
    assert "headerRow.append(headerInfo, legend)" not in rendered


def test_strategy_lab_has_one_baseline_chart_only_for_now() -> None:
    source = (ROOT / "tradingdesk_ui/charts/lightweight/pnl_strategy_lab_simple_v5.py").read_text(encoding="utf-8")

    assert 'data={"payload": payload, "mode": "baseline"}' in source
    assert '"mode": "advanced"' not in source


def test_tradingdesk_mounts_simple_strategy_lab_without_execution_changes() -> None:
    source = (ROOT / "tradingdesk_automanage_panel_v2.py").read_text(encoding="utf-8")

    assert "pnl_strategy_lab_simple_v5" in source
    assert "render_strategy_lab_pnl_v5" in source
    assert "request_manual_target_v2" not in source
    assert "switch_live_strategy_v2" not in source
