from autotrader_v2_execution_vnext_v1 import plan_v2_execution_vnext_v1


def test_flat_to_short_opens_exact_delta():
    step = plan_v2_execution_vnext_v1(actual_inventory=0, desired_inventory=-0.03, amount_step=0.01)
    assert (step.action, step.side, step.amount, step.expected_inventory) == ("OPEN", "Sell", 0.03, -0.03)


def test_flat_to_long_opens_exact_delta():
    step = plan_v2_execution_vnext_v1(actual_inventory=0, desired_inventory=0.02, amount_step=0.01)
    assert (step.action, step.side, step.amount, step.expected_inventory) == ("OPEN", "Buy", 0.02, 0.02)


def test_same_side_growth_is_add():
    step = plan_v2_execution_vnext_v1(actual_inventory=0.02, desired_inventory=0.05, amount_step=0.01)
    assert (step.action, step.side, step.amount, step.expected_inventory) == ("ADD", "Buy", 0.03, 0.05)


def test_same_side_shrink_is_reduce():
    step = plan_v2_execution_vnext_v1(actual_inventory=-0.05, desired_inventory=-0.02, amount_step=0.01)
    assert (step.action, step.side, step.amount, step.expected_inventory) == ("REDUCE", "Buy", 0.03, -0.02)


def test_flat_target_closes_observed_inventory():
    step = plan_v2_execution_vnext_v1(actual_inventory=0.04, desired_inventory=0, amount_step=0.01)
    assert (step.action, step.side, step.amount, step.expected_inventory) == ("CLOSE", "Sell", 0.04, 0.0)


def test_reversal_closes_first_and_does_not_open_opposite_side_same_cycle():
    step = plan_v2_execution_vnext_v1(actual_inventory=0.04, desired_inventory=-0.02, amount_step=0.01)
    assert (step.action, step.side, step.amount, step.expected_inventory) == ("CLOSE", "Sell", 0.04, 0.0)


def test_matching_inventory_is_noop():
    assert plan_v2_execution_vnext_v1(actual_inventory=-0.02, desired_inventory=-0.02, amount_step=0.01) is None


def test_sub_step_delta_is_noop_until_legal_amount_exists():
    assert plan_v2_execution_vnext_v1(actual_inventory=0.02, desired_inventory=0.025, amount_step=0.01) is None
