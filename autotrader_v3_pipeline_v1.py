from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol, Sequence

from autotrader_v3_domain import (
    AccountBoundaryV3,
    CapitalAllocationV3,
    ControlModeV3,
    DecisionSnapshotV3,
    TargetInventoryV3,
)


@dataclass(frozen=True, slots=True)
class TraderV3:
    trader_id: str
    account: AccountBoundaryV3
    strategy_key: str
    mode: ControlModeV3 = ControlModeV3.DETERMINISTIC
    capital_allocation: CapitalAllocationV3 = CapitalAllocationV3(100.0)


@dataclass(frozen=True, slots=True)
class TargetTransformV3:
    stage: str
    source: str
    before: TargetInventoryV3
    after: TargetInventoryV3
    reason: str


@dataclass(frozen=True, slots=True)
class PipelineResultV3:
    snapshot: DecisionSnapshotV3
    transforms: tuple[TargetTransformV3, ...]


class TargetModifierV3(Protocol):
    key: str

    def apply(self, trader: TraderV3, target: TargetInventoryV3) -> tuple[TargetInventoryV3, str]:
        ...


class RiskGovernorV3(Protocol):
    key: str

    def approve(self, trader: TraderV3, target: TargetInventoryV3) -> tuple[TargetInventoryV3, str]:
        ...


class PassThroughRiskGovernorV3:
    key = "risk-pass-through-v3"

    def approve(self, trader: TraderV3, target: TargetInventoryV3) -> tuple[TargetInventoryV3, str]:
        return target, "pass-through"


def _record_transform(
    transforms: list[TargetTransformV3],
    *,
    stage: str,
    source: str,
    before: TargetInventoryV3,
    after: TargetInventoryV3,
    reason: str,
) -> None:
    transforms.append(TargetTransformV3(stage, source, before, after, reason))


def evaluate_trader_v3(
    *,
    trader: TraderV3,
    base_target: TargetInventoryV3,
    actual_inventory: TargetInventoryV3,
    supervisor: TargetModifierV3 | None = None,
    modifiers: Sequence[TargetModifierV3] = (),
    risk_governor: RiskGovernorV3 | None = None,
) -> PipelineResultV3:
    """Pure v3 decision pipeline. It cannot submit, persist or reconcile orders."""
    transforms: list[TargetTransformV3] = []
    effective = base_target

    if supervisor is not None:
        proposed, reason = supervisor.apply(trader, effective)
        if trader.mode is ControlModeV3.ADVISORY:
            _record_transform(
                transforms, stage="SUPERVISOR_ADVISORY", source=supervisor.key,
                before=effective, after=proposed, reason=reason,
            )
        elif trader.mode in {
            ControlModeV3.SUPERVISOR,
            ControlModeV3.AUTONOMOUS,
            ControlModeV3.GOD_MODE,
        }:
            before = effective
            effective = proposed
            _record_transform(
                transforms, stage="SUPERVISOR", source=supervisor.key,
                before=before, after=effective, reason=reason,
            )

    for modifier in modifiers:
        before = effective
        effective, reason = modifier.apply(trader, effective)
        _record_transform(
            transforms, stage="MODIFIER", source=modifier.key,
            before=before, after=effective, reason=reason,
        )

    governor = risk_governor or PassThroughRiskGovernorV3()
    risk_target, reason = governor.approve(trader, effective)
    _record_transform(
        transforms, stage="RISK", source=governor.key,
        before=effective, after=risk_target, reason=reason,
    )

    snapshot = DecisionSnapshotV3(
        trader_id=trader.trader_id,
        account=trader.account,
        mode=trader.mode,
        strategy_key=trader.strategy_key,
        capital_allocation=trader.capital_allocation,
        base_target=base_target,
        effective_target=effective,
        risk_approved_target=risk_target,
        actual_inventory=actual_inventory,
        pending_delta=risk_target.delta_from(actual_inventory.amount),
    )
    return PipelineResultV3(snapshot=snapshot, transforms=tuple(transforms))


__all__ = [
    "PassThroughRiskGovernorV3",
    "PipelineResultV3",
    "RiskGovernorV3",
    "TargetModifierV3",
    "TargetTransformV3",
    "TraderV3",
    "evaluate_trader_v3",
]
