from __future__ import annotations

from pathlib import Path


def test_tradingdesk_renders_compact_automanage_context_in_right_controls():
    source = Path("pages/0_TradingDesk.py").read_text(encoding="utf-8")
    assert "chart_column, controls_column = st.columns([4.8, 1.45]" in source
    assert 'with st.expander(f"AutoManage · {market}", expanded=True):' in source
    assert "render_tradingdesk_automanage_panel_v2(baseline_context)" in source
    assert source.index('with st.expander(f"AutoManage · {market}"') < source.index('with st.expander("Status"')


def test_automanage_panel_is_generic_product_strategy_enrollment_not_order_submitter():
    source = Path("tradingdesk_automanage_panel_v2.py").read_text(encoding="utf-8")
    assert "_position_observations_v2" in source
    assert "resolve_saxo_automanage_product_v2" in source
    assert "int(product.market_id) == int(context.market_id)" in source
    assert "AUTOTRADER_STRATEGIES_V2" in source
    assert "enroll_strategy_position_v2" in source
    assert "EXECUTION_MODE_LIVE" in source
    assert "EXECUTION_MODE_SHADOW" in source
    assert "Kjør den andre MACD-strategien som shadow for sammenligning" in source
    assert "Startkapital" in source
    assert "Pilotkapital" in source
    assert "Realisert LIVE" in source
    assert "AutoTrade · entry/re-entry" in source
    assert "disabled=True" in source
    assert "session.post" not in source
    assert "_post_once" not in source
    assert "CREATE TABLE" not in source
    assert "4912" not in source


def test_automanage_panel_shows_same_basis_strategy_scorecard():
    source = Path("tradingdesk_automanage_panel_v2.py").read_text(encoding="utf-8")
    assert "load_shadow_benchmark_state_v2" in source
    assert "Strategitest" in source
    assert "Paper P/L" in source
    assert "samme canonical 30m-bars og startkapital" in source
    assert "faktisk Saxo-P/L føres separat" in source


def test_automanage_enrollment_requires_explicit_user_acknowledgement():
    source = Path("tradingdesk_automanage_panel_v2.py").read_text(encoding="utf-8")
    assert "Jeg vil at PriceGauger skal AutoManage denne eksakte LIVE-posisjonen med valgt strategi." in source
    assert 'disabled=not acknowledge' in source
    assert '"Aktiver AutoManage"' in source
    assert '"Stopp denne piloten"' in source
