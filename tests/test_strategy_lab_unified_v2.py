from __future__ import annotations

from pathlib import Path

from tradingdesk_ui.charts.lightweight.pnl_strategy_lab_unified_v2 import _STRATEGY_LAB_UNIFIED_JS


ROOT = Path(__file__).resolve().parents[1]


def test_strategy_lab_baseline_restores_shared_relative_return_pane() -> None:
    rendered = _STRATEGY_LAB_UNIFIED_JS

    # Inspect the actual JS handed to the Streamlit component. Market, LIVE, the
    # provenance carrier and baseline controls must all render on pane 0.
    assert "for (const model of Array.from(payload.baseline_models || []))" in rendered
    assert "live = chart.addSeries" in rendered
    assert "const carrier = chart.addSeries" in rendered
    assert rendered.count("}}, 0);") >= 4


def test_strategy_lab_mobile_pinch_is_reserved_for_native_chart_scaling() -> None:
    rendered = _STRATEGY_LAB_UNIFIED_JS

    assert "touchAction: 'pan-y'" in rendered
    assert "event.touches?.length >= 2" in rendered
    assert "event.preventDefault()" in rendered
    assert "passive: false" in rendered
    assert "pinch: true" in rendered


def test_tradingdesk_mounts_unified_strategy_lab_without_execution_changes() -> None:
    source = (ROOT / "tradingdesk_automanage_panel_v2.py").read_text(encoding="utf-8")

    assert "pnl_strategy_lab_unified_v2" in source
    assert "render_strategy_lab_pnl_v2" in source
    assert "request_manual_target_v2" not in source
    assert "switch_live_strategy_v2" not in source
