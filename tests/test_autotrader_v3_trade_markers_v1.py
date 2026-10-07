from pathlib import Path

from autotrader_v3_trade_markers_v1 import marker_direction_v3

from pathlib import Path

def test_v3_marker_projection_reads_only_execution_events():
    source=Path("autotrader_v3_trade_markers_v1.py").read_text(encoding="utf-8")
    assert "FROM autotrader_v3_execution_events e" in source
    assert "FROM autotrader_v3_order_guard" not in source
    assert "nearest_bar" not in source
    assert 'source="AUTOTRADER_V3"' in source

def test_v3_ledger_derives_flat_from_reconciled_inventory():
    source=Path("autotrader_v3_execution_events_v1.py").read_text(encoding="utf-8")
    assert "THEN 'FLAT'" in source
    assert "inventory_before" in source and "inventory_after" in source

def test_canonical_chart_marker_loader_includes_v3_projection():
    source=Path("autotrader_trade_markers_v2.py").read_text(encoding="utf-8")
    assert "load_v3_trade_markers_v1" in source
    assert "markers.extend(load_v3_trade_markers_v1(market_name))" in source


def test_v3_marker_direction_follows_broker_side_for_partial_reductions():
    assert marker_direction_v3(
        action="REDUCE", side="Buy", resulting_direction="SHORT"
    ) == "LONG"
    assert marker_direction_v3(
        action="REDUCE", side="Sell", resulting_direction="LONG"
    ) == "SHORT"


def test_v3_full_close_remains_flat_marker():
    assert marker_direction_v3(
        action="CLOSE", side="Buy", resulting_direction="FLAT"
    ) == "FLAT"


def test_v3_add_and_open_keep_expected_side_arrows():
    assert marker_direction_v3(
        action="ADD", side="Sell", resulting_direction="SHORT"
    ) == "SHORT"
    assert marker_direction_v3(
        action="OPEN", side="Buy", resulting_direction="LONG"
    ) == "LONG"
