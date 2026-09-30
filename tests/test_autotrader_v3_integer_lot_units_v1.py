from decimal import Decimal

from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_execution_plan_v1 import plan_execution_v3
from autotrader_v3_domain import AccountBoundaryV3, CapitalAllocationV3, ControlModeV3, DecisionSnapshotV3


def test_inventory_canonicalizes_float_noise_to_integer_centilots():
    inventory = TargetInventoryV3(0.03 - 0.02)
    assert inventory.units == 1
    assert inventory.amount_decimal == Decimal("0.01")


def test_signed_inventory_uses_exact_integer_centilots():
    assert TargetInventoryV3(-0.03).units == -3
    assert TargetInventoryV3(0.10).units == 10


def _snapshot(actual, target):
    return DecisionSnapshotV3(
        "t", AccountBoundaryV3("a", 1, "CfdOnIndex"), ControlModeV3.DETERMINISTIC,
        "macd-trailing-v1", CapitalAllocationV3(100), TargetInventoryV3(target),
        TargetInventoryV3(target), TargetInventoryV3(target), TargetInventoryV3(actual),
        TargetInventoryV3(target).delta_from(actual),
    )


def test_execution_delta_is_integer_units_not_float_subtraction():
    plan = plan_execution_v3(_snapshot(-0.03, -0.02))
    assert len(plan.steps) == 1
    assert plan.steps[0].action == "REDUCE"
    assert plan.steps[0].units == 1
    assert plan.steps[0].amount_decimal == Decimal("0.01")
