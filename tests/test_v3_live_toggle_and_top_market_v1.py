from pathlib import Path


def test_shared_v3_controls_expose_live_authority_via_control_plane():
    source=Path("autotrader_v3_instance_controls_ui_v1.py").read_text(encoding="utf-8")
    assert "from autotrader_v3_control_plane_v1 import authority_state_v3,set_live_enabled_v3" in source
    assert "Slå LIVE på" in source
    assert "Slå LIVE av" in source
    assert "set_live_enabled_v3(trader_id,True,account_id=instance.account_id)" in source
    assert "set_live_enabled_v3(trader_id,False,account_id=instance.account_id)" in source
    assert "set_live_authority_v3" not in source


def test_tradingdesk_market_selector_is_top_level_and_unique():
    source=Path("pages/0_TradingDesk.py").read_text(encoding="utf-8")
    selector='market = st.selectbox(\n        "Marked",\n        available_markets,\n        key=MARKET_STATE_KEY'
    assert selector in source
    assert source.count('key=MARKET_STATE_KEY') == 1
    assert source.index("market_title_col, market_select_col") < source.index("chart_column, controls_column")
    assert 'st.markdown(f"### {market}")' in source
    assert 'st.caption(f"Analyseinnstillinger for {market}.")' in source
