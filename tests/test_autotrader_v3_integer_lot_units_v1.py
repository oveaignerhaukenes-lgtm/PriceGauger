from decimal import Decimal

from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_execution_plan_v1 import plan_execution_v3
from tests.test_autotrader_v3_execution_plan_v1 import snapshot


def test_inventory_canonicalizes_float_noise_to_integer_centilots():
    inventory = TargetInventoryV3(0.03 - 0.02)
    assert inventory.units == 1
    assert inventory.amount_decimal == Decimal("0.01")


def test_signed_inventory_uses_exact_integer_centilots():
    assert TargetInventoryV3(-0.03).units == -3
    assert TargetInventoryV3(0.10).units == 10


def test_execution_delta_is_integer_units_not_float_subtraction():
    plan = plan_execution_v3(snapshot(-0.03, -0.02))
    assert len(plan.steps) == 1
    assert plan.steps[0].action == "REDUCE"
    assert plan.steps[0].units == 1
    assert plan.steps[0].amount_decimal == Decimal("0.01")
