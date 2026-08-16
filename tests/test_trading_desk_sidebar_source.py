from pathlib import Path


def test_tradingdesk_chart_settings_live_in_right_control_panel() -> None:
    source = Path("pages/0_TradingDesk.py").read_text(encoding="utf-8")

    assert "with st.sidebar:" not in source
    assert "with controls_column:" in source
    assert 'market = st.selectbox("Marked", available_markets' in source
    assert 'st.selectbox("Vindu", [6, 12, 24, 48]' in source
    assert 'st.radio("Overlay-akse"' in source
    assert 'st.multiselect("Sammenlign med", overlay_options)' in source
    assert '"Vis indikatorer",' in source
    assert '"Total grafhøyde"' in source
    assert '"Hovedgrafens andel"' in source


def test_tradingdesk_has_direct_timeframe_buttons() -> None:
    source = Path("pages/0_TradingDesk.py").read_text(encoding="utf-8")

    assert 'QUICK_TIMEFRAMES = ("1m", "5m", "10m", "15m", "30m", "1h")' in source
    assert "on_click=_select_timeframe" in source
    assert "args=(value,)" in source


def test_plotly_graph_operators_are_vertical_on_right_edge() -> None:
    source = Path("pages/0_TradingDesk.py").read_text(encoding="utf-8")

    assert 'div[data-testid="stPlotlyChart"] .modebar' in source
    assert 'right: .35rem !important' in source
    assert 'flex-direction: column !important' in source


def test_tradingdesk_market_analysis_root_is_v2_only() -> None:
    source = Path("pages/0_TradingDesk.py").read_text(encoding="utf-8")

    assert "load_trading_desk_contexts_v2" in source
    assert "render_companion_panel_v2(view)" in source
    assert "render_v2_forecast_chart(view)" in source
    assert "configured_instruments" not in source
    assert "Legacy analyse/forecast brukes ikke som skjult fallback" in source
