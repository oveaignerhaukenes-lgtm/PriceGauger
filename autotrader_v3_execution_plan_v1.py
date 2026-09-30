from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from autotrader_v3_domain import DecisionSnapshotV3


@dataclass(frozen=True, slots=True, init=False)
class ExecutionStepV3:
    action: str
    units: int
    direction: str
    requires_flat_confirmation: bool
    reason: str

    def __init__(self, action: str, amount: float, direction: str,
                 requires_flat_confirmation: bool, reason: str) -> None:
        inventory = TargetInventoryV3(abs(amount))
        object.__setattr__(self, "action", action)
        object.__setattr__(self, "units", abs(inventory.units))
        object.__setattr__(self, "direction", direction)
        object.__setattr__(self, "requires_flat_confirmation", requires_flat_confirmation)
        object.__setattr__(self, "reason", reason)

    @classmethod
    def from_units(cls, action: str, units: int, direction: str,
                   requires_flat_confirmation: bool, reason: str) -> "ExecutionStepV3":
        obj = object.__new__(cls)
        object.__setattr__(obj, "action", action)
        object.__setattr__(obj, "units", abs(int(units)))
        object.__setattr__(obj, "direction", direction)
        object.__setattr__(obj, "requires_flat_confirmation", requires_flat_confirmation)
        object.__setattr__(obj, "reason", reason)
        return obj

    @property
    def amount_decimal(self) -> Decimal:
        return Decimal(self.units) / Decimal("100")

    @property
    def amount(self) -> float:
        return float(self.amount_decimal)


@dataclass(frozen=True, slots=True)
class ExecutionPlanV3:
    trader_id: str
    steps: tuple[ExecutionStepV3, ...]

    @property
    def summary(self) -> str:
        if not self.steps:
            return "HOLD"
        return " → ".join(
            f"{step.action} {step.direction} {step.amount:.2f}" for step in self.steps
        )


def plan_execution_v3(snapshot: DecisionSnapshotV3, *, epsilon: float = 1e-9) -> ExecutionPlanV3:
    """Translate approved inventory into a dry-run reconciliation plan.

    This module deliberately has no broker imports, persistence or side effects.
    Reversals are represented as CLOSE -> CONFIRM_FLAT -> OPEN, preserving the
    hardened v2 execution invariant before a future adapter is allowed to submit.
    """
    actual = snapshot.actual_inventory.units
    target = snapshot.risk_approved_target.units
    if target == actual:
        return ExecutionPlanV3(snapshot.trader_id, ())

    actual_sign = 1 if actual > 0 else -1 if actual < 0 else 0
    target_sign = 1 if target > 0 else -1 if target < 0 else 0
    direction = lambda sign: "LONG" if sign > 0 else "SHORT"

    if target_sign == 0:
        return ExecutionPlanV3(snapshot.trader_id, (
            ExecutionStepV3.from_units("CLOSE", abs(actual), direction(actual_sign), True, "approved target is FLAT"),
        ))

    if actual_sign == 0:
        return ExecutionPlanV3(snapshot.trader_id, (
            ExecutionStepV3.from_units("OPEN", abs(target), direction(target_sign), False, "Saxo is FLAT; open approved target"),
        ))

    if actual_sign != target_sign:
        return ExecutionPlanV3(snapshot.trader_id, (
            ExecutionStepV3("CLOSE", abs(actual), direction(actual_sign), True, "opposite exposure must close first"),
            ExecutionStepV3.from_units("CONFIRM_FLAT", 0, "FLAT", True, "observe exact Saxo product FLAT before open"),
            ExecutionStepV3("OPEN", abs(target), direction(target_sign), False, "open approved opposite target only after FLAT"),
        ))

    delta = abs(target) - abs(actual)
    if delta > 0:
        return ExecutionPlanV3(snapshot.trader_id, (
            ExecutionStepV3.from_units("ADD", delta, direction(target_sign), False, "increase same-side inventory to approved target"),
        ))
    return ExecutionPlanV3(snapshot.trader_id, (
        ExecutionStepV3.from_units("REDUCE", abs(delta), direction(actual_sign), False, "reduce same-side inventory to approved target"),
    ))


__all__ = ["ExecutionPlanV3", "ExecutionStepV3", "plan_execution_v3"]
