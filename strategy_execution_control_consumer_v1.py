"""Bind Strategy Lab management intents to the canonical CLOSE lifecycle.

Only a position opened and reconciled by the same frozen scope may be closed.
Other management actions have no safe per-scope execution path yet and are
explicitly rejected instead of pretending to have modified broker protection.
"""
from __future__ import annotations

import logging
from uuid import NAMESPACE_URL, uuid5

from autotrader_fast_live_runtime_v2 import _exact_product_observation
from autotrader_managed_positions_v1 import is_position_managed_v1
from autotrader_manual_close_v1 import request_manual_close_v1
from autotrader_strategy_enrollment_v2 import load_strategy_enrollment_v2
from database import connect, using_postgres
from strategy_execution_budget_v1 import ensure_strategy_open_provenance_schema_v1, scoped_open_cap_v1
from strategy_execution_control_v1 import ensure_strategy_execution_control_schema_v1


LOGGER = logging.getLogger("pricegauger.strategy_execution_controls")
TERMINAL = {"BLOCKED", "REJECTED", "SUPERSEDED"}


def _set_status(control_id: str, *, status: str, request_id: str | None = None,
                reason: str | None = None, expected_status: str = "PENDING") -> None:
    with connect() as db:
        db.execute("""UPDATE pg_v2_strategy_execution_controls
          SET status=?, request_id=COALESCE(?,request_id), block_reason=?
          WHERE control_id=? AND status=?""",
          (status, request_id, reason, control_id, expected_status))


def consume_strategy_execution_controls_v1(*, observations: tuple) -> int:
    """Process bounded intents; execution still belongs to existing workers."""
    if not using_postgres():
        return 0
    ensure_strategy_execution_control_schema_v1()
    ensure_strategy_open_provenance_schema_v1()
    with connect() as db:
        controls = [dict(row) for row in db.execute("""SELECT * FROM pg_v2_strategy_execution_controls
            WHERE status IN ('PENDING','ACCEPTED') ORDER BY created_at ASC""").fetchall()]
    processed = 0
    for control in controls:
        control_id = str(control["control_id"])
        try:
            if control["status"] == "ACCEPTED":
                if not control.get("request_id"):
                    _set_status(control_id, status="REJECTED", reason="CLOSE_REQUEST_ID_MISSING", expected_status="ACCEPTED")
                    continue
                with connect() as db:
                    row = db.execute("SELECT status FROM pg_v2_autotrader_execution_requests WHERE request_id=?",
                                     (str(control["request_id"]),)).fetchone()
                result = None if row is None else dict(row)["status"]
                if result == "RECONCILED":
                    _set_status(control_id, status="EXECUTED", expected_status="ACCEPTED")
                elif result in TERMINAL or result is None:
                    _set_status(control_id, status="REJECTED", reason=f"CANONICAL_CLOSE_{result or 'MISSING'}", expected_status="ACCEPTED")
                processed += 1
                continue

            if control["action"] != "CLOSE":
                _set_status(control_id, status="REJECTED", reason="SCOPED_MANAGEMENT_ACTION_NOT_AVAILABLE")
                processed += 1
                continue
            with connect() as db:
                row = db.execute("""SELECT p.*, r.status AS open_status, r.strategy_key AS execution_strategy_key,
                    r.budget_amount, r.budget_currency, r.signal, a.amount AS open_amount
                    FROM pg_v2_strategy_open_provenance p
                    JOIN pg_v2_autotrader_execution_requests r ON r.request_id=p.request_id
                    LEFT JOIN pg_v2_autotrader_live_open_attempts a ON a.request_id=r.request_id
                    WHERE p.scope_id=? AND p.plan_id=? AND p.strategy_key=?""",
                    (control["scope_id"], control["plan_id"], control["strategy_key"])).fetchone()
            if row is None:
                _set_status(control_id, status="REJECTED", reason="NO_EXECUTED_OPEN_IN_THIS_SCOPE")
                processed += 1
                continue
            source = dict(row)
            request = {"request_id": str(source["request_id"]), "pilot_key": source["pilot_key"],
                "strategy_key": source["execution_strategy_key"], "account_id": source["account_id"],
                "uic": source["uic"], "asset_type": source["asset_type"],
                "budget_amount": source["budget_amount"], "budget_currency": source["budget_currency"],
                "signal": source["signal"]}
            scoped_open_cap_v1(request, account_currency="NOK")
            if source["open_status"] in TERMINAL:
                _set_status(control_id, status="REJECTED", reason="SCOPED_OPEN_NOT_EXECUTED")
                processed += 1
                continue
            if source["open_status"] != "RECONCILED":
                continue
            enrollment = load_strategy_enrollment_v2(str(source["pilot_key"]))
            if enrollment is None or enrollment.strategy_key != source["execution_strategy_key"]:
                _set_status(control_id, status="REJECTED", reason="SCOPED_ENROLLMENT_CHANGED")
                processed += 1
                continue
            stable_request_id = str(uuid5(NAMESPACE_URL, f"fast-live-execution|{control_id}|CLOSE|FLAT"))
            with connect() as db:
                already = db.execute("""SELECT request_id FROM pg_v2_autotrader_execution_requests
                  WHERE request_id=? AND pilot_key=? AND action='CLOSE'""",
                  (stable_request_id, enrollment.pilot_key)).fetchone()
            if already is not None:
                _set_status(control_id, status="ACCEPTED", request_id=stable_request_id)
                processed += 1
                continue
            observed = _exact_product_observation(enrollment, observations)
            if (observed is None or not is_position_managed_v1(observed)
                or observed.net_position_id != enrollment.anchor_net_position_id
                or source["open_amount"] is None
                or abs(float(observed.amount) - float(source["open_amount"])) > 1e-9):
                _set_status(control_id, status="REJECTED", reason="SCOPED_POSITION_BASIS_CHANGED")
                processed += 1
                continue
            # The control UUID is the deterministic intent id, so a worker retry
            # cannot create a second CLOSE request after an acknowledgement crash.
            result = request_manual_close_v1(enrollment, observation=observed, intent_event_id=control_id)
            if result.request_id:
                _set_status(control_id, status="ACCEPTED", request_id=result.request_id)
            else:
                _set_status(control_id, status="REJECTED", reason="CANONICAL_CLOSE_NOT_QUEUED")
            processed += 1
        except ValueError as exc:
            LOGGER.warning("Strategy Lab control blocked id=%s: %s", control_id, exc)
            _set_status(control_id, status="REJECTED", reason=str(exc)[:250])
            processed += 1
        except Exception:
            # A temporary broker/database problem must not claim execution or
            # discard an explicit user intent. Stable UUID makes retries safe.
            LOGGER.exception("Strategy Lab control retry id=%s", control_id)
    return processed
