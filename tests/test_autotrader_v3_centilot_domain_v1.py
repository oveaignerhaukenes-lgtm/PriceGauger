from decimal import Decimal

from autotrader_v3_domain import TargetInventoryV3, centilots_v3, lots_v3


def test_centilot_conversion_is_exact_at_domain_boundary():
    assert centilots_v3(0.03) == 3
    assert centilots_v3(-0.02) == -2
    assert lots_v3(3) == Decimal("0.03")


def test_float_noise_collapses_to_same_integer_inventory():
    assert centilots_v3(0.020000000000000004) == 2
    assert TargetInventoryV3(0.020000000000000004).units == 2
    assert TargetInventoryV3(0.020000000000000004).amount == 0.02


def test_delta_is_computed_in_integer_units():
    target=TargetInventoryV3(0.0)
    assert target.delta_from(-0.020000000000000004) == 0.02
