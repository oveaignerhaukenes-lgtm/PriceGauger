import pytest
from autotrader_v3_position_reconcile_v1 import reconcile_position_v3


def test_pending_buy_confirms_only_expected_inventory():
    r=reconcile_position_v3(expected_inventory=-.02,submitted_amount=.01,submitted_side='Buy',actual_inventory=-.02)
    assert r.state=='CONFIRMED' and r.before==pytest.approx(-.03)


def test_pending_buy_waits_without_retry_at_before_inventory():
    r=reconcile_position_v3(expected_inventory=-.02,submitted_amount=.01,submitted_side='Buy',actual_inventory=-.03)
    assert r.state=='WAIT'
    assert 'never retry' in r.detail


def test_manual_or_external_mutation_is_conflict_not_success():
    r=reconcile_position_v3(expected_inventory=-.02,submitted_amount=.01,submitted_side='Buy',actual_inventory=.03)
    assert r.state=='CONFLICT'
    assert r.actual==pytest.approx(.03)


def test_invalid_pending_evidence_fails_closed():
    with pytest.raises(ValueError):
        reconcile_position_v3(expected_inventory=0,submitted_amount=0,submitted_side='Buy',actual_inventory=0)
