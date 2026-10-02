from __future__ import annotations

"""Engine-neutral, read-only execution diagnostics.

The model intentionally does not create schema or mutate authority. It exposes the
persisted ownership/runtime/request evidence needed to answer "what owns this
account and what happened to the last order?" without opening implementation tables
from Streamlit code.
"""

from dataclasses import dataclass

from autotrader_engine_account_ownership_v1 import load_account_owner_v1
from database import connect


@dataclass(frozen=True, slots=True)
class ExecutionDiagnosticV1:
    engine_id: str
    owner_key: str
    account_id: str
    uic: int
    asset_type: str
    runtime_status: str | None
    runtime_detail: str | None
    runtime_updated_at: str | None
    request_key: str | None
    request_state: str | None
    broker_order_id: str | None
    expected_inventory: float | None
    submitted_amount: float | None
    submitted_side: str | None
    request_detail: str | None
    request_updated_at: str | None


def _row_dict(row, columns: tuple[str, ...]) -> dict:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row)
    except Exception:
        return dict(zip(columns, row))


def load_execution_diagnostic_v1(
    *,
    account_id: str,
    uic: int,
    asset_type: str,
    owner_key: str,
    engine_id: str,
    db_path: str = "pricegauger.db",
) -> ExecutionDiagnosticV1:
    ownership = load_account_owner_v1(account_id, db_path=db_path)
    if ownership is not None and (
        ownership.engine_id != str(engine_id).strip().upper()
        or ownership.owner_key != str(owner_key).strip()
    ):
        raise RuntimeError(
            f"diagnostic boundary mismatch: account {account_id} is owned by "
            f"{ownership.engine_id}/{ownership.owner_key}"
        )

    runtime = {}
    request = {}
    with connect(db_path) as db:
        try:
            row = db.execute(
                """SELECT status,detail,updated_at
                   FROM autotrader_v3_live_runtime_state WHERE trader_id=?""",
                (owner_key,),
            ).fetchone()
            runtime = _row_dict(row, ("status", "detail", "updated_at"))
        except Exception:
            runtime = {}
        try:
            row = db.execute(
                """SELECT request_key,state,broker_order_id,expected_inventory,
                          submitted_amount,submitted_side,detail,updated_at
                   FROM autotrader_v3_order_guard
                   WHERE account_id=? AND uic=? AND asset_type=?
                   ORDER BY updated_at DESC LIMIT 1""",
                (account_id, int(uic), asset_type),
            ).fetchone()
            request = _row_dict(
                row,
                (
                    "request_key", "state", "broker_order_id", "expected_inventory",
                    "submitted_amount", "submitted_side", "detail", "updated_at",
                ),
            )
        except Exception:
            request = {}

    return ExecutionDiagnosticV1(
        engine_id=str(engine_id).strip().upper(),
        owner_key=str(owner_key).strip(),
        account_id=str(account_id).strip(),
        uic=int(uic),
        asset_type=str(asset_type).strip(),
        runtime_status=runtime.get("status"),
        runtime_detail=runtime.get("detail"),
        runtime_updated_at=str(runtime.get("updated_at")) if runtime.get("updated_at") is not None else None,
        request_key=request.get("request_key"),
        request_state=request.get("state"),
        broker_order_id=request.get("broker_order_id"),
        expected_inventory=float(request["expected_inventory"]) if request.get("expected_inventory") is not None else None,
        submitted_amount=float(request["submitted_amount"]) if request.get("submitted_amount") is not None else None,
        submitted_side=request.get("submitted_side"),
        request_detail=request.get("detail"),
        request_updated_at=str(request.get("updated_at")) if request.get("updated_at") is not None else None,
    )


__all__ = ["ExecutionDiagnosticV1", "load_execution_diagnostic_v1"]
