from pathlib import Path


def test_tradingdesk_chart_settings_live_in_right_control_panel() -> None:
    source = Path("pages/0_TradingDesk.py").read_text(encoding="utf-8")

    assert "with st.sidebar:" not in source
    assert "with controls_column:" in source
    assert 'market = st.selectbox(' in source
    assert '"Marked",' in source
    assert 'st.selectbox("Vindu", [6, 12, 24, 48]' in source
    assert 'st.radio("Overlay-akse"' in source
    assert 'st.multiselect("Sammenlign med", overlay_options)' in source
    assert '"Vis indikatorer",' in source
    assert '"Total grafhøyde"' in source
    assert '"Hovedgrafens andel"' in source


def test_tradingdesk_timeframe_workbar_is_above_live_chart() -> None:
    source = Path("pages/0_TradingDesk.py").read_text(encoding="utf-8")
    toolbar = Path("tradingdesk_ui/charts/lightweight/toolbar.py").read_text(encoding="utf-8")

    assert "LIGHTWEIGHT_TIMEFRAMES_V1" in source
    assert "render_lightweight_timeframe_toolbar_v1(state_key=TIMEFRAME_STATE_KEY)" in source
    assert '("1m", "2m", "5m", "10m", "15m", "30m")' in toolbar
    assert "st.segmented_control(" in toolbar
    assert "wrap=False" in toolbar
    assert "required=True" in toolbar


def test_tradingdesk_persists_market_in_query_and_auto_refreshes_fragments_by_default() -> None:
    source = Path("pages/0_TradingDesk.py").read_text(encoding="utf-8")

    assert 'MARKET_STATE_KEY = "tradingdesk-v2-market"' in source
    assert 'requested_market = str(st.query_params.get("market", "")' in source
    assert 'st.query_params["market"] = selected' in source
    assert 'st.session_state[AUTO_REFRESH_STATE_KEY] = True' in source
    assert 'analysis_fragment(run_every=f"{V2_ANALYSIS_REFRESH_SECONDS}s")' in source
    assert 'chart_fragment(run_every=f"{LIVE_CHART_BASE_REFRESH_SECONDS}s")' in source
    assert 'overlay_fragment(run_every=f"{LIVE_CANDLE_OVERLAY_REFRESH_SECONDS}s")' in source


def test_tradingdesk_updates_recent_forming_candle_directly_in_lightweight_browser_series() -> None:
    source = Path("pages/0_TradingDesk.py").read_text(encoding="utf-8")

    assert "forming_store.load(market=market)" in source
    assert "forming_candle_event_age_seconds(candidate)" in source
    assert "render_lightweight_live_update_v1(" in source
    assert "Sekundbevegelsen oppdaterer Lightweight-serien direkte" in source
    assert "render_live_candle_overlay_v2" not in source


def test_plotly_graph_operators_remain_available_for_non_live_charts() -> None:
    source = Path("pages/0_TradingDesk.py").read_text(encoding="utf-8")

    assert 'div[data-testid="stPlotlyChart"] .modebar' in source
    assert 'right: .35rem !important' in source
    assert 'top: .35rem !important' in source
    assert 'flex-direction: row !important' in source


def test_tradingdesk_live_chart_is_direct_lightweight_not_plotly_bridge() -> None:
    source = Path("pages/0_TradingDesk.py").read_text(encoding="utf-8")
    live_chart = source.split("def _render_live_chart() -> None:", 1)[1].split(
        "def _render_lightweight_live_update()", 1
    )[0]

    assert "build_lightweight_direct_live_payload_v1(" in live_chart
    assert "render_lightweight_direct_live_v1(" in live_chart
    assert "st.plotly_chart(" not in live_chart
    assert "build_trading_desk_figure(" not in live_chart
    assert "render_lightweight_plotly_bridge_v1" not in source
    assert "render_lightweight_presentation_cleanup_v1" not in source


def test_tradingdesk_market_analysis_root_is_v2_only() -> None:
    source = Path("pages/0_TradingDesk.py").read_text(encoding="utf-8")

    assert "load_trading_desk_contexts_v2" in source
    assert "render_companion_panel_v2(view)" in source
    assert "render_v2_forecast_chart(view)" in source
    assert "configured_instruments" not in source
    assert "Legacy analyse/forecast brukes ikke som skjult fallback" in source
