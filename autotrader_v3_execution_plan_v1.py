from __future__ import annotations

from dataclasses import dataclass

from autotrader_v3_domain import DecisionSnapshotV3


@dataclass(frozen=True, slots=True)
class ExecutionStepV3:
    action: str
    amount: float
    direction: str
    requires_flat_confirmation: bool
    reason: str


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
    actual = float(snapshot.actual_inventory.amount)
    target = float(snapshot.risk_approved_target.amount)
    if abs(target - actual) <= epsilon:
        return ExecutionPlanV3(snapshot.trader_id, ())

    actual_sign = 1 if actual > epsilon else -1 if actual < -epsilon else 0
    target_sign = 1 if target > epsilon else -1 if target < -epsilon else 0
    direction = lambda sign: "LONG" if sign > 0 else "SHORT"

    if target_sign == 0:
        return ExecutionPlanV3(snapshot.trader_id, (
            ExecutionStepV3("CLOSE", abs(actual), direction(actual_sign), True, "approved target is FLAT"),
        ))

    if actual_sign == 0:
        return ExecutionPlanV3(snapshot.trader_id, (
            ExecutionStepV3("OPEN", abs(target), direction(target_sign), False, "Saxo is FLAT; open approved target"),
        ))

    if actual_sign != target_sign:
        return ExecutionPlanV3(snapshot.trader_id, (
            ExecutionStepV3("CLOSE", abs(actual), direction(actual_sign), True, "opposite exposure must close first"),
            ExecutionStepV3("CONFIRM_FLAT", 0.0, "FLAT", True, "observe exact Saxo product FLAT before open"),
            ExecutionStepV3("OPEN", abs(target), direction(target_sign), False, "open approved opposite target only after FLAT"),
        ))

    delta = abs(target) - abs(actual)
    if delta > epsilon:
        return ExecutionPlanV3(snapshot.trader_id, (
            ExecutionStepV3("ADD", delta, direction(target_sign), False, "increase same-side inventory to approved target"),
        ))
    return ExecutionPlanV3(snapshot.trader_id, (
        ExecutionStepV3("REDUCE", abs(delta), direction(actual_sign), False, "reduce same-side inventory to approved target"),
    ))


__all__ = ["ExecutionPlanV3", "ExecutionStepV3", "plan_execution_v3"]
