from __future__ import annotations

"""Read-only bridge used to prove vNext plans before LIVE cutover."""

from dataclasses import dataclass

from autotrader_v2_execution_readiness_v1 import execution_readiness_v2_vnext_v1
from autotrader_v2_execution_vnext_v1 import V2ExecutionMutationV1, plan_v2_execution_vnext_v1


@dataclass(frozen=True, slots=True)
class V2ShadowPlanV1:
    status: str
    detail: str
    mutation: V2ExecutionMutationV1 | None


def shadow_plan_v2_vnext_v1(enrollment, *, actual_inventory: float, desired_inventory: float, amount_step: float, db_path: str = "pricegauger.db") -> V2ShadowPlanV1:
    readiness = execution_readiness_v2_vnext_v1(enrollment, db_path=db_path)
    if not readiness.ready:
        return V2ShadowPlanV1(readiness.status, readiness.detail, None)
    mutation = plan_v2_execution_vnext_v1(
        actual_inventory=actual_inventory,
        desired_inventory=desired_inventory,
        amount_step=amount_step,
    )
    if mutation is None:
        return V2ShadowPlanV1("READY", "Exact inventory already matches target or delta is below legal amount step", None)
    return V2ShadowPlanV1(
        "READY",
        f"shadow {mutation.action} {mutation.side} {mutation.amount:g}; actual={actual_inventory:g} desired={desired_inventory:g} expected={mutation.expected_inventory:g}",
        mutation,
    )
