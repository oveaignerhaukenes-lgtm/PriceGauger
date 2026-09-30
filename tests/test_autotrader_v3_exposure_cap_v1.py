from decimal import Decimal as D

import pytest

from autotrader_v3_exposure_cap_v1 import V3ExposureCap, clamp_target_to_cap


def test_signed_targets_are_bounded_by_budget_and_rounded_down():
    cap = V3ExposureCap(D("2000"), D("50"), D("3041.09"))
    assert cap.max_quantity == D("0.32")
    assert clamp_target_to_cap(D("0.50"), cap) == D("0.32")
    assert clamp_target_to_cap(D("-0.50"), cap) == D("-0.32")
    assert clamp_target_to_cap(D("-0.12"), cap) == D("-0.12")


def test_zero_allocation_blocks_new_exposure():
    cap = V3ExposureCap(D("2000"), D("0"), D("3041.09"))
    assert clamp_target_to_cap(D("0.03"), cap) == 0


@pytest.mark.parametrize("kwargs", [
    {"budget_nok": D("0"), "exposure_pct": D("50"), "unit_notional_nok": D("100")},
    {"budget_nok": D("100"), "exposure_pct": D("101"), "unit_notional_nok": D("100")},
    {"budget_nok": D("100"), "exposure_pct": D("50"), "unit_notional_nok": D("0")},
])
def test_invalid_inputs_rejected(kwargs):
    with pytest.raises(ValueError):
        V3ExposureCap(**kwargs)
