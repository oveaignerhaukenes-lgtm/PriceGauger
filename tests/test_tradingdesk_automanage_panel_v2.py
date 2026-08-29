from __future__ import annotations

from pathlib import Path


def test_tradingdesk_renders_compact_automanage_context_in_right_controls():
    source = Path("pages/0_TradingDesk.py").read_text(encoding="utf-8")
    assert "chart_column, controls_column = st.columns([4.8, 1.45]" in source
    assert 'with st.expander(f"AutoManage · {market}", expanded=True):' in source
    assert "render_tradingdesk_automanage_panel_v2(baseline_context)" in source
    assert source.index('with st.expander(f"AutoManage · {market}"') < source.index('with st.expander("Status"')


def test_automanage_panel_is_exact_live_position_strategy_enrollment_not_order_submitter():
    source = Path("tradingdesk_automanage_panel_v2.py").read_text(encoding="utf-8")
    assert "_position_observations_v2" in source
    assert "resolve_live_pilot_binding_v2" in source
    assert "int(binding.market_id) == int(context.market_id)" in source
    assert "enroll_macd_flip_position_v2" in source
    assert "MACD_FLIP_STRATEGY_V2" in source
    assert "30m MACD flip" in source
    assert "Startkapital" in source
    assert "Pilotkapital" in source
    assert "Realisert" in source
    assert "AutoTrade · flip/re-entry" in source
    assert "disabled=True" in source
    assert "session.post" not in source
    assert "_post_once" not in source
    assert "CREATE TABLE" not in source


def test_automanage_enrollment_requires_explicit_user_acknowledgement():
    source = Path("tradingdesk_automanage_panel_v2.py").read_text(encoding="utf-8")
    assert "Jeg vil at PriceGauger skal AutoManage denne eksakte LIVE-posisjonen." in source
    assert 'disabled=not acknowledge' in source
    assert '"Aktiver AutoManage"' in source
    assert '"Stopp AutoManage"' in source
