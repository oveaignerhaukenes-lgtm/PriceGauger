from __future__ import annotations

import pytest

from autotrader_v3_domain import AccountBoundaryV3, CapitalAllocationV3, ControlModeV3, TargetInventoryV3
from autotrader_v3_pipeline_v1 import TraderV3, evaluate_trader_v3


class _Supervisor:
    key = "test-supervisor"

    def apply(self, trader, target):
        return TargetInventoryV3(target.amount / 2), "halve exposure"


class _TakeProfit:
    key = "test-take-profit"

    def apply(self, trader, target):
        return TargetInventoryV3(target.amount - 0.01), "trail one tranche"


class _Risk:
    key = "test-risk"

    def approve(self, trader, target):
        capped = max(-0.03, min(0.03, target.amount))
        return TargetInventoryV3(capped), "cap at 0.03"


def _trader(mode=ControlModeV3.DETERMINISTIC):
    return TraderV3(
        trader_id="t-1",
        account=AccountBoundaryV3("acct", 42, "CfdOnIndex"),
        strategy_key="macd-trailing-v1",
        mode=mode,
        capital_allocation=CapitalAllocationV3(35),
    )


def test_deterministic_mode_does_not_apply_supervisor():
    result = evaluate_trader_v3(
        trader=_trader(),
        base_target=TargetInventoryV3(0.08),
        actual_inventory=TargetInventoryV3(0.01),
        supervisor=_Supervisor(),
        modifiers=(_TakeProfit(),),
        risk_governor=_Risk(),
    )
    assert result.snapshot.base_target.amount == pytest.approx(0.08)
    assert result.snapshot.effective_target.amount == pytest.approx(0.07)
    assert result.snapshot.risk_approved_target.amount == pytest.approx(0.03)
    assert result.snapshot.pending_delta == pytest.approx(0.02)
    assert all(item.stage != "SUPERVISOR" for item in result.transforms)


def test_advisory_records_counterfactual_but_cannot_change_effective_target():
    result = evaluate_trader_v3(
        trader=_trader(ControlModeV3.ADVISORY),
        base_target=TargetInventoryV3(0.08),
        actual_inventory=TargetInventoryV3(0.0),
        supervisor=_Supervisor(),
    )
    assert result.snapshot.effective_target.amount == pytest.approx(0.08)
    advisory = [x for x in result.transforms if x.stage == "SUPERVISOR_ADVISORY"]
    assert len(advisory) == 1
    assert advisory[0].after.amount == pytest.approx(0.04)


@pytest.mark.parametrize("mode", [ControlModeV3.SUPERVISOR, ControlModeV3.AUTONOMOUS, ControlModeV3.GOD_MODE])
def test_authority_modes_may_transform_target_but_still_pass_through_risk(mode):
    result = evaluate_trader_v3(
        trader=_trader(mode),
        base_target=TargetInventoryV3(0.08),
        actual_inventory=TargetInventoryV3(0.01),
        supervisor=_Supervisor(),
        risk_governor=_Risk(),
    )
    assert result.snapshot.effective_target.amount == pytest.approx(0.04)
    assert result.snapshot.risk_approved_target.amount == pytest.approx(0.03)
    assert result.snapshot.pending_delta == pytest.approx(0.02)
    assert [x.stage for x in result.transforms] == ["SUPERVISOR", "RISK"]


def test_pipeline_is_pure_target_math_and_preserves_capital_allocation():
    result = evaluate_trader_v3(
        trader=_trader(),
        base_target=TargetInventoryV3(-0.02),
        actual_inventory=TargetInventoryV3(0.01),
    )
    assert result.snapshot.capital_allocation.tradeable_pct == pytest.approx(35)
    assert result.snapshot.pending_delta == pytest.approx(-0.03)
