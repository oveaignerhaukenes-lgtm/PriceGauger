from __future__ import annotations

from pathlib import Path


def test_ai_baseline_materializer_uses_freshness_capped_series() -> None:
    source = Path("autotrader_strategy_series_materializer_v1.py").read_text(encoding="utf-8")
    assert "load_ai_baseline_fresh_series_v1" in source
    assert "legacy_without_ai" in source
    assert "AI_BASELINE_FRESH_SERIES_VERSION" in source


def test_fresh_ai_baseline_goes_flat_after_max_decision_age() -> None:
    source = Path("autotrader_ai_baseline_fresh_series_v1.py").read_text(encoding="utf-8")
    assert "previous_at + MAX_DECISION_AGE" in source
    assert "position_state=STATE_FLAT" in source
    assert "stays FLAT until a later real decision arrives" in source


def test_strategy_lab_matches_primary_chart_gesture_contract() -> None:
    source = Path("tradingdesk_ui/charts/lightweight/pnl_strategy_lab_simple_v5.py").read_text(encoding="utf-8")
    for expected in (
        "mouseWheel: true",
        "pinch: true",
        "pressedMouseMove: true",
        "horzTouchDrag: true",
        "axisPressedMouseMove: { time: true, price: true }",
        "axisDoubleClickReset: { time: true, price: true }",
        "kineticScroll: { mouse: true, touch: true }",
        "fixLeftEdge: false, fixRightEdge: false",
        "hoveredSeriesOnTop: true",
    ):
        assert expected in source
