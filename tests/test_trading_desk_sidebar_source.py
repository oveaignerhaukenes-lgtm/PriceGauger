from pathlib import Path


def test_tradingdesk_chart_settings_live_in_sidebar() -> None:
    source = Path("pages/0_TradingDesk.py").read_text(encoding="utf-8")

    assert "with st.sidebar:" in source
    assert 'st.selectbox("Marked", available_markets)' in source
    assert 'st.selectbox(\n        "Vindu"' in source
    assert 'st.radio(\n        "Overlay-akse"' in source
    assert 'st.multiselect("Sammenlign med", overlay_options)' in source
    assert '"Indikatorer",' in source


def test_tradingdesk_has_direct_minute_timeframe_buttons() -> None:
    source = Path("pages/0_TradingDesk.py").read_text(encoding="utf-8")

    assert 'QUICK_TIMEFRAMES = ("1m", "5m", "10m", "15m", "30m")' in source
    assert "on_click=_select_timeframe" in source
    assert 'args=("1h",)' in source
