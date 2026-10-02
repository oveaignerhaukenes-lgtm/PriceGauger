from pathlib import Path


def test_pending_lookup_and_actual_inventory_use_exact_enrollment_boundary():
    source=Path('autotrader_v3_live_runtime_v1.py').read_text()
    assert "pending_order_v3(account_id=e.account_id,uic=e.uic" in source
    assert "asset_type=e.asset_type,db_path=db_path" in source
    assert "account_id=e.account_id,uic=int(e.uic),asset_type=e.asset_type" in source
