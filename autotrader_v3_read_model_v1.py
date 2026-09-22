from __future__ import annotations

from autotrader_risk_control_v2 import PositionObservationV2
from autotrader_strategy_enrollment_v2 import StrategyEnrollmentV2
from autotrader_v3_domain import (
    AccountBoundaryV3,
    CapitalAllocationV3,
    ControlModeV3,
    DecisionSnapshotV3,
    TargetInventoryV3,
    signed_inventory_v3,
)


def _exact_observation_v3(
    enrollment: StrategyEnrollmentV2,
    observations: tuple[PositionObservationV2, ...],
) -> PositionObservationV2 | None:
    matches = tuple(
        item
        for item in observations
        if item.account_id == enrollment.account_id
        and int(item.uic) == int(enrollment.uic)
        and item.asset_type == enrollment.asset_type
    )
    if len(matches) > 1:
        raise RuntimeError("v3 read model found multiple Saxo positions inside one account boundary")
    return matches[0] if matches else None


def observe_v2_as_v3_v1(
    enrollment: StrategyEnrollmentV2,
    observations: tuple[PositionObservationV2, ...],
) -> DecisionSnapshotV3:
    """Read-only bridge: represent current v2/Saxo truth using v3 contracts.

    This function deliberately creates no execution request and performs no persistence.
    Until native v3 strategies exist, all three target stages adopt actual inventory.
    That makes the first v3 slice observational and incapable of causing a CLOSE.
    """
    observed = _exact_observation_v3(enrollment, observations)
    actual = (
        TargetInventoryV3(0.0)
        if observed is None
        else signed_inventory_v3(direction=observed.direction, amount=observed.amount)
    )
    boundary = AccountBoundaryV3(
        account_id=enrollment.account_id,
        uic=int(enrollment.uic),
        asset_type=enrollment.asset_type,
    )
    return DecisionSnapshotV3(
        trader_id=enrollment.pilot_key,
        account=boundary,
        mode=ControlModeV3.DETERMINISTIC,
        strategy_key=enrollment.strategy_key,
        capital_allocation=CapitalAllocationV3(100.0),
        base_target=actual,
        effective_target=actual,
        risk_approved_target=actual,
        actual_inventory=actual,
        pending_delta=0.0,
    )


__all__ = ["observe_v2_as_v3_v1"]
