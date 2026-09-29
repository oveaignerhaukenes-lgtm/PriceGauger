from autotrader_v3_order_guard_v1 import UNRESOLVED

def test_unresolved_states_are_fail_closed():
    assert {'RESERVED','SUBMITTING','SUBMITTED','UNKNOWN'} == set(UNRESOLVED)
