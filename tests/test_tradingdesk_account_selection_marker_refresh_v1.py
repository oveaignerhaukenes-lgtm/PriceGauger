from pathlib import Path

DESK=Path("tradingdesk_automanager_simple_v1.py").read_text(encoding="utf-8")
CHART=Path("pages/0_TradingDesk.py").read_text(encoding="utf-8")
ADAPTER=Path("tradingdesk_ui/charts/lightweight/adapters.py").read_text(encoding="utf-8")
RENDERER=Path("tradingdesk_ui/charts/lightweight/simple_live_v2.py").read_text(encoding="utf-8")


def test_account_selection_is_applied_to_controller_and_bootstrap():
    assert 'for tab, engine_key in zip(tabs, ("V2", "V3")):' in DESK
    assert "_active_live_for_context_v1(context, account_id=account_id)" in DESK
    assert "bootstrap = _bootstrap_candidate_v1(context, observations, account_id=selected_account)" in DESK
    assert "and (account_id is None or item.account_id == account_id)" in DESK
    assert "Ingen automatisk overtakelse av posisjoner" in DESK


def test_trade_markers_are_refreshed_not_one_time_drawings():
    assert "@st.fragment(run_every=\"1000ms\")" in CHART
    assert "trade_markers=_load_trade_markers()" in CHART
    assert "ttl=3" in ADAPTER
    assert "entry.markers?.setMarkers?.(markerPayload());" in RENDERER
    assert "pg_v2_saxo_manual_trade_marker_sync" in CHART
