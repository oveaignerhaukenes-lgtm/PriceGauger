from __future__ import annotations

"""Readiness boundary for V2 execution vNext."""

from dataclasses import dataclass

from autotrader_engine_account_ownership_v1 import ENGINE_V2, load_account_owner_v1


@dataclass(frozen=True, slots=True)
class V2ExecutionReadinessV1:
    ready: bool
    status: str
    detail: str


def execution_readiness_v2_vnext_v1(enrollment, *, db_path: str = "pricegauger.db") -> V2ExecutionReadinessV1:
    account_id = str(enrollment.account_id).strip()
    pilot_key = str(enrollment.pilot_key).strip()
    if not account_id:
        return V2ExecutionReadinessV1(False, "BLOCKED", "V2 enrollment has no account_id")
    owner = load_account_owner_v1(account_id, db_path=db_path)
    if owner is None:
        return V2ExecutionReadinessV1(False, "BLOCKED", "V2 account has no canonical engine owner")
    if owner.engine_id != ENGINE_V2:
        return V2ExecutionReadinessV1(False, "BLOCKED", f"Account is owned by {owner.engine_id}, not V2")
    if str(owner.owner_key) != pilot_key:
        return V2ExecutionReadinessV1(False, "BLOCKED", "V2 account is owned by a different V2 runtime")
    if int(enrollment.uic) <= 0 or not str(enrollment.asset_type).strip():
        return V2ExecutionReadinessV1(False, "BLOCKED", "V2 enrollment lacks exact Saxo instrument boundary")
    return V2ExecutionReadinessV1(True, "READY", "Exact V2 account + instrument ownership proven")
