from pathlib import Path


def test_v2_manual_origin_survives_saxo_netposition_id_rollover():
    source=Path("manual_saxo_trade_markers_v1.py").read_text()
    start=source.index("def manual_position_has_provenance_v1")
    body=source[start:start+1800]
    assert "account_id = ? AND uic = ? AND asset_type = ?" in body
    assert "position_id = ?" in body
    assert "INTERVAL '24 hours'" in body
    assert "autotrader_v3_order_guard" in body
