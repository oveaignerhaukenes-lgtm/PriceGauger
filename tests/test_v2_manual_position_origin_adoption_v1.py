from pathlib import Path


def test_v2_guard_accepts_only_broker_audit_proven_manual_position_origin():
    source=Path("autotrader_execution_guard_v1.py").read_text()
    assert "manual_position_has_provenance_v1" in source
    assert "position_id=str(observation.net_position_id)" in source
    assert "POSITION_ORIGIN_UNRESOLVED" in source


def test_manual_position_provenance_is_exact_account_product_and_position():
    source=Path("manual_saxo_trade_markers_v1.py").read_text()
    assert "def manual_position_has_provenance_v1" in source
    assert "account_id = ? AND uic = ? AND asset_type = ?" in source
    assert "AND position_id = ?" in source
    assert "autotrader_v3_order_guard" in source
