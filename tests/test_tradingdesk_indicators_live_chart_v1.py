from pathlib import Path


def test_tradingdesk_live_chart_restores_selected_indicators():
    source = Path("pages/0_TradingDesk.py").read_text(encoding="utf-8")
    body = source.split("def _load_standalone_chart_payload():", 1)[1].split(
        "def _render_live_chart(", 1
    )[0]
    assert "technical, selected_indicators = _load_chart_indicators_v1(closed)" in body
    assert "indicators=technical" in body
    assert "indicator_names=selected_indicators" in body
    assert "indicator_timeframes={INDICATOR_MACD: timeframe}" in body
    assert "indicators=None" not in body
    assert "indicator_names=()" not in body


def test_tradingdesk_indicator_warmup_preserves_visible_window_vwap():
    source = Path("pages/0_TradingDesk.py").read_text(encoding="utf-8")
    helper = source.split("def _load_chart_indicators_v1(closed):", 1)[1].split(
        "def _load_standalone_chart_payload():", 1
    )[0]
    assert "INDICATOR_WARMUP_PERIODS" in helper
    assert "calculate_indicators(warmup_bars)" in helper
    assert "clip_indicators(" in helper
    assert "visible_technical = calculate_indicators(closed)" in helper
    assert "replace(technical, vwap=visible_technical.vwap)" in helper


def test_tradingdesk_live_chart_uses_user_chart_layout():
    source = Path("pages/0_TradingDesk.py").read_text(encoding="utf-8")
    body = source.split("def _load_standalone_chart_payload():", 1)[1].split(
        "def _render_live_chart(", 1
    )[0]
    assert "chart_height=chart_height" in body
    assert "price_panel_share=float(price_panel_pct) / 100.0" in body
