from __future__ import annotations

from indicator_guide_v1 import guide_for_indicator_v1, quick_indicator_read_v1
from trading_desk_indicators import (
    INDICATOR_MACD,
    INDICATOR_RSI,
    INDICATOR_VWAP,
    IndicatorPoint,
    TechnicalIndicators,
)


def _point(value: float) -> IndicatorPoint:
    return IndicatorPoint(bar_time="2026-09-07T00:00:00Z", value=value)


def test_macd_quick_read_describes_side_and_cooling():
    technical = TechnicalIndicators(
        macd=(_point(1.0),),
        macd_signal=(_point(0.5),),
        macd_histogram=(_point(0.8), _point(0.5)),
    )
    assert quick_indicator_read_v1(INDICATOR_MACD, technical, latest_close=100.0) == (
        "MACD er bullish · avstanden kjølner."
    )


def test_rsi_quick_read_does_not_call_high_level_an_automatic_reversal():
    technical = TechnicalIndicators(rsi=(_point(74.2),))
    assert quick_indicator_read_v1(INDICATOR_RSI, technical, latest_close=100.0) == (
        "RSI 74.2 · høyt momentum."
    )
    assert "revers" not in guide_for_indicator_v1(INDICATOR_RSI).short.lower()


def test_vwap_quick_read_uses_price_relation():
    technical = TechnicalIndicators(vwap=(_point(99.5),))
    assert quick_indicator_read_v1(INDICATOR_VWAP, technical, latest_close=100.0) == (
        "Pris over VWAP (99.5)."
    )


def test_tradingdesk_mounts_indicator_guide_beside_chart_and_ai_is_cached_only():
    from pathlib import Path
    desk = Path("pages/0_TradingDesk.py").read_text(encoding="utf-8")
    standalone = Path("pages/0_Live_Chart.py").read_text(encoding="utf-8")
    assert "load_live_test_snapshot_v1(" in desk and "load_live_test_snapshot_v1(" in standalone
    assert "def _load_standalone_chart_payload():" in desk
    assert "trade_markers=()," in desk
    assert 'render_lightweight_simple_live_v2(payload, key=chart_key, refresh_only=refresh_only)' in desk
    assert 'lambda: _render_live_chart(refresh_only=True)' in desk

def test_indicator_guide_exposes_more_information_without_provider_dependency():
    source = open("indicator_guide_v1.py", encoding="utf-8").read()
    assert 'st.popover("Fortell mer"' in source
    assert 'st.toggle(\n        "AI-vurdering"' in source
    assert "Technical Interpreter" in source
    assert "load_latest_indicator_ai_v1" in source
    assert "requests." not in source.lower()
