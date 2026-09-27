"""Immutable Strategy Lab provenance for canonical OPEN requests.

The table has no broker authority. The existing OPEN worker enforces its notional
ceiling after Saxo's account-currency precheck and again before submitting.
"""
from __future__ import annotations

from dataclasses import asdict
from math import isclose

from database import connect
from strategy_execution_adapter_v1 import validate_strategy_execution_binding_v1
from strategy_execution_scope_v1 import ExecutionAdapterScopeV1, assert_adapter_scope_match_v1


def ensure_strategy_open_provenance_schema_v1() -> None:
    with connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS pg_v2_strategy_open_provenance (
          request_id UUID PRIMARY KEY REFERENCES pg_v2_autotrader_execution_requests(request_id),
          scope_id TEXT NOT NULL, strategy_key TEXT NOT NULL, plan_id TEXT NOT NULL,
          handoff_id TEXT NOT NULL, pilot_key TEXT NOT NULL, account_id TEXT NOT NULL,
          uic BIGINT NOT NULL, asset_type TEXT NOT NULL, budget_nok DOUBLE PRECISION NOT NULL,
          exposure_pct DOUBLE PRECISION NOT NULL, max_notional_nok DOUBLE PRECISION NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""")
        db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS pg_v2_strategy_open_scope_unique
          ON pg_v2_strategy_open_provenance(scope_id)""")


def scoped_open_cap_v1(request: dict, *, account_currency: str) -> float | None:
    """Fail closed for corrupt/stale scoped requests; leave ordinary requests alone."""
    ensure_strategy_open_provenance_schema_v1()
    with connect() as db:
        row = db.execute(
            "SELECT * FROM pg_v2_strategy_open_provenance WHERE request_id=?",
            (str(request["request_id"]),),
        ).fetchone()
    if row is None:
        if str(request.get("signal", "")).startswith("STRATEGY_LAB_"):
            raise ValueError("STRATEGY_LAB_PROVENANCE_MISSING")
        return None
    p = dict(row)
    if account_currency.upper() != "NOK" or str(request["budget_currency"]).upper() != "NOK":
        raise ValueError("STRATEGY_LAB_REQUIRES_NOK_ACCOUNT")
    expected = ExecutionAdapterScopeV1(**{k: p[k] for k in ExecutionAdapterScopeV1.__dataclass_fields__})
    binding = validate_strategy_execution_binding_v1(**asdict(expected))
    assert_adapter_scope_match_v1(expected, binding.scope)
    from autotrader_manage_control_v1 import auto_manage_enabled_v1, position_management_enabled_v1
    from autotrader_strategy_enrollment_v2 import load_strategy_enrollment_v2
    enrollment = load_strategy_enrollment_v2(expected.pilot_key)
    if (enrollment is None or enrollment.strategy_key != binding.execution_strategy_key
        or auto_manage_enabled_v1(enrollment) or not position_management_enabled_v1(enrollment)):
        raise ValueError("STRATEGY_LAB_PILOT_AUTHORITY_CHANGED")
    cap = expected.max_exposure_nok
    if (str(request["pilot_key"]) != expected.pilot_key
        or str(request.get("signal")) != "STRATEGY_LAB_APPROVED_OPEN"
        or str(request["strategy_key"]) != binding.execution_strategy_key
        or str(request["account_id"]) != expected.account_id
        or int(request["uic"]) != expected.uic
        or str(request["asset_type"]) != expected.asset_type
        or not isclose(float(p["max_notional_nok"]), cap, rel_tol=0, abs_tol=1e-8)
        or not isclose(float(request["budget_amount"]), cap, rel_tol=0, abs_tol=1e-8)):
        raise ValueError("STRATEGY_LAB_REQUEST_PROVENANCE_MISMATCH")
    return cap


def load_scoped_open_status_v1(scope_id: str) -> tuple[str, str | None]:
    """Read-only UI summary of the one OPEN request owned by a plan scope."""
    ensure_strategy_open_provenance_schema_v1()
    with connect() as db:
        row = db.execute("""SELECT r.status, r.request_id, r.block_reason FROM pg_v2_strategy_open_provenance p
            JOIN pg_v2_autotrader_execution_requests r ON r.request_id=p.request_id
            WHERE p.scope_id=?""", (scope_id,)).fetchone()
    if row is None:
        # This only means the plan is ready for an explicit pilot selection;
        # queueing still validates all canonical authority and broker gates.
        return "READY(FOR_PILOT_SELECTION)", None
    data = dict(row)
    status = str(data["status"]).upper()
    if status == "RECONCILED":
        from strategy_execution_control_v1 import ensure_strategy_execution_control_schema_v1
        ensure_strategy_execution_control_schema_v1()
        with connect() as db:
            closed = db.execute("""SELECT control_id FROM pg_v2_strategy_execution_controls
                WHERE scope_id=? AND action='CLOSE' AND status='EXECUTED' LIMIT 1""",
                (scope_id,)).fetchone()
        if closed is not None:
            return "CLOSED", str(data["request_id"])
    display = {"PENDING":"QUEUED", "APPROVED":"QUEUED", "SUBMITTING":"QUEUED",
        "ORDER_ACCEPTED":"QUEUED", "RECONCILED":"LIVE", "REJECTED":"BLOCKED(REJECTED)",
        "BLOCKED":"BLOCKED(ORDER)", "SUPERSEDED":"BLOCKED(SUPERSEDED)",
        "UNCERTAIN":"BLOCKED(UNCERTAIN)"}.get(status, f"BLOCKED({status})")
    if status in {"REJECTED", "BLOCKED", "UNCERTAIN"} and data.get("block_reason"):
        display += f": {data['block_reason']}"
    return display, str(data["request_id"])
