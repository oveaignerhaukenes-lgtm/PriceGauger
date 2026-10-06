from pathlib import Path

def test_manual_sync_knows_durable_v2_v3_broker_order_ids():
    source=Path("manual_saxo_trade_markers_v1.py").read_text(); assert "SELECT guard.broker_order_id" in source; assert "autotrader_v3_order_guard" in source; assert "NOT EXISTS" in source

def test_v3_chart_reads_canonical_execution_ledger_not_order_state():
    legacy=Path("autotrader_trade_markers_v2.py").read_text(); v3=Path("autotrader_v3_trade_markers_v1.py").read_text(); ledger=Path("autotrader_v3_execution_events_v1.py").read_text(); guard=Path("autotrader_v3_order_guard_v1.py").read_text()
    assert "load_v3_trade_markers_v1" in legacy; assert "markers.extend(load_v3_trade_markers_v1(market_name))" in legacy
    assert "FROM autotrader_v3_execution_events e" in v3; assert "FROM autotrader_v3_order_guard" not in v3
    assert "pg_v3_execution_event_trigger" in ledger; assert "AFTER UPDATE OF state ON autotrader_v3_order_guard" in ledger
    assert "ensure_v3_execution_event_schema_v1" in guard; assert 'source="AUTOTRADER_V3"' in v3

def test_chart_uses_compact_manual_m_and_distinct_v2_v3_colors():
    contract=Path("tradingdesk_ui/charts/lightweight/contract.py").read_text(); live=Path("tradingdesk_ui/charts/lightweight/live_update.py").read_text(); overlay=Path("tradingdesk_ui/charts/lightweight/trade_marker_overlay_v2.py").read_text()
    for source in (contract,live,overlay):
        assert "(MANUAL)" not in source; assert "AUTOTRADER_V3" in source; assert "#a855f7" in source; assert "#0ea5e9" in source
    assert 'label = "M"' in contract; assert "manualSaxo ? 'M' : ''" in live
