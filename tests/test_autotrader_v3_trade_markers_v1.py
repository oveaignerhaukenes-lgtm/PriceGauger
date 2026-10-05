from pathlib import Path


def test_v3_marker_projection_reads_durable_reconciled_order_guard():
    source = Path("autotrader_v3_trade_markers_v1.py").read_text(encoding="utf-8")
    assert "FROM autotrader_v3_order_guard AS guard" in source
    assert "guard.state = 'RECONCILED'" in source
    assert "enrollment.account_id = guard.account_id" in source
    assert "enrollment.uic = guard.uic" in source
    assert "enrollment.asset_type = guard.asset_type" in source
    assert 'source="AUTOTRADER_V3"' in source


def test_v3_zero_expected_inventory_projects_flat_marker():
    source = Path("autotrader_v3_trade_markers_v1.py").read_text(encoding="utf-8")
    assert 'direction = "FLAT" if expected is not None' in source


def test_canonical_chart_marker_loader_includes_v3_projection():
    source = Path("autotrader_trade_markers_v2.py").read_text(encoding="utf-8")
    assert "load_v3_trade_markers_v1" in source
    assert "markers.extend(load_v3_trade_markers_v1(market_name))" in source
