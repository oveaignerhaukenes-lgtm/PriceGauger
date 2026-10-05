from autotrader_v2_reconcile_vnext_v1 import reconcile_v2_vnext_v1


def test_expected_inventory_confirms():
    assert reconcile_v2_vnext_v1(before_inventory=0, expected_inventory=-0.02, actual_inventory=-0.02).state == "CONFIRMED"


def test_unchanged_inventory_waits_without_retry():
    assert reconcile_v2_vnext_v1(before_inventory=0, expected_inventory=-0.02, actual_inventory=0).state == "WAIT"


def test_unexplained_inventory_is_conflict():
    assert reconcile_v2_vnext_v1(before_inventory=0, expected_inventory=-0.02, actual_inventory=-0.01).state == "CONFLICT"
