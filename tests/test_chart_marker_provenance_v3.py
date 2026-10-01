from pathlib import Path


def test_manual_sync_knows_durable_v2_v3_broker_order_ids():
    source=Path("manual_saxo_trade_markers_v1.py").read_text()
    assert "SELECT guard.broker_order_id" in source
    assert "autotrader_v3_order_guard" in source
    assert "NOT EXISTS" in source


def test_reconciled_durable_orders_are_projected_with_engine_provenance():
    source=Path("autotrader_trade_markers_v2.py").read_text()
    assert "_durable_guard_markers_v2" in source
    assert "'AUTOTRADER_V2'" in source
    assert "'AUTOTRADER_V3'" in source
    assert "guard.state = 'RECONCILED'" in source


def test_chart_uses_compact_manual_m_and_distinct_v2_v3_colors():
    contract=Path("tradingdesk_ui/charts/lightweight/contract.py").read_text()
    live=Path("tradingdesk_ui/charts/lightweight/live_update.py").read_text()
    overlay=Path("tradingdesk_ui/charts/lightweight/trade_marker_overlay_v2.py").read_text()
    for source in (contract,live,overlay):
        assert "(MANUAL)" not in source
        assert "AUTOTRADER_V3" in source
        assert "#a855f7" in source
        assert "#0ea5e9" in source
    assert 'label = "M"' in contract
    assert "manualSaxo ? 'M' : ''" in live
