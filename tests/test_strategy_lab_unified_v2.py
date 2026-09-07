from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_strategy_lab_baseline_restores_shared_relative_return_pane() -> None:
    source = (
        ROOT / "tradingdesk_ui" / "charts" / "lightweight" / "pnl_strategy_lab_unified_v2.py"
    ).read_text(encoding="utf-8")

    # The adapter must move LIVE, its provenance carrier, and baseline controls to
    # pane 0, where the market reference already lives. Assert executable rewrite
    # targets instead of prose/comment wording.
    assert "live = chart.addSeries" in source
    assert "const carrier = chart.addSeries" in source
    assert "for (const model of Array.from(payload.baseline_models || []))" in source
    assert source.count("}}, 0);") >= 3
    assert "build_strategy_lab_payload_v1" in source


def test_strategy_lab_mobile_pinch_is_reserved_for_native_chart_scaling() -> None:
    source = (
        ROOT / "tradingdesk_ui" / "charts" / "lightweight" / "pnl_strategy_lab_unified_v2.py"
    ).read_text(encoding="utf-8")

    assert "touchAction: 'pan-y'" in source
    assert "event.touches?.length >= 2" in source
    assert "event.preventDefault()" in source
    assert "passive: false" in source
    assert "handleScale.pinch" in source


def test_tradingdesk_mounts_unified_strategy_lab_without_execution_changes() -> None:
    source = (ROOT / "tradingdesk_automanage_panel_v2.py").read_text(encoding="utf-8")

    assert "pnl_strategy_lab_unified_v2" in source
    assert "render_strategy_lab_pnl_v2" in source
    assert "request_manual_target_v2" not in source
    assert "switch_live_strategy_v2" not in source
