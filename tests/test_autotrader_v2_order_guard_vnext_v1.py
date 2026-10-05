import autotrader_v2_order_guard_vnext_v1 as guard


def test_exact_boundary_allows_only_one_unresolved_order(tmp_path):
    db = str(tmp_path / "guard.db")
    first = guard.reserve_order_v2_vnext_v1(
        request_key="one", trader_id="pilot", account_id="lager", uic=4912,
        asset_type="CfdOnIndex", actual_inventory=0, expected_inventory=-0.02,
        submitted_amount=0.02, submitted_side="Sell", db_path=db)
    second = guard.reserve_order_v2_vnext_v1(
        request_key="two", trader_id="pilot", account_id="lager", uic=4912,
        asset_type="CfdOnIndex", actual_inventory=0, expected_inventory=-0.02,
        submitted_amount=0.02, submitted_side="Sell", db_path=db)
    assert first is True
    assert second is False
    pending = guard.pending_order_v2_vnext_v1(account_id="lager", uic=4912, asset_type="CfdOnIndex", db_path=db)
    assert pending["request_key"] == "one"


def test_reconciled_order_releases_boundary(tmp_path):
    db = str(tmp_path / "guard.db")
    assert guard.reserve_order_v2_vnext_v1(
        request_key="one", trader_id="pilot", account_id="lager", uic=4912,
        asset_type="CfdOnIndex", actual_inventory=0, expected_inventory=-0.02,
        submitted_amount=0.02, submitted_side="Sell", db_path=db)
    guard.mark_order_v2_vnext_v1(request_key="one", state="RECONCILED", db_path=db)
    assert guard.reserve_order_v2_vnext_v1(
        request_key="two", trader_id="pilot", account_id="lager", uic=4912,
        asset_type="CfdOnIndex", actual_inventory=-0.02, expected_inventory=0,
        submitted_amount=0.02, submitted_side="Buy", db_path=db)
