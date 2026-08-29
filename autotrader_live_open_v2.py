from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import os
import time
from typing import Any

from autotrader_cadence_v2 import sleep_to_fixed_start_cadence_v2
from autotrader_entry_policy_v2 import require_entry_policy_v2
from autotrader_live_close_v1 import (
    _position_netting_mode,
    _post_once,
    _require_live_client,
)
from autotrader_managed_positions_v1 import enroll_position_v1
from autotrader_open_sizing_v2 import (
    EntrySizingError,
    find_largest_legal_entry_v2,
    live_open_order_payload_v2,
    precheck_entry_amount_v2,
)
from autotrader_pilot_equity_v2 import load_pilot_equity_v2
from autotrader_risk_control_v2 import PositionObservationV2, _position_observations_v2
from autotrader_schema_v2 import ensure_autotrader_schema_v2
from autotrader_strategy_enrollment_v2 import (
    ENTRY_MODE_APPROVAL_REQUIRED,
    ENTRY_MODE_AUTO,
    ENTRY_MODE_MANUAL_ONLY,
    EXECUTION_MODE_LIVE,
    load_strategy_enrollment_v2,
)
from database import connect, using_postgres
from saxo_provider import SaxoError, SaxoInstrument


LOGGER = logging.getLogger("pricegauger.autotrader.live_open_v2")
CODE_GATE_ENV = "PRICEGAUGER_AUTOTRADER_LIVE_OPEN_CODE_ENABLED"
OPEN_SIGNAL_MAX_AGE = timedelta(minutes=90)

STATUS_PENDING = "PENDING"
STATUS_APPROVED = "APPROVED"
STATUS_SUPERSEDED = "SUPERSEDED"
STATUS_SUBMITTING = "SUBMITTING"
STATUS_ORDER_ACCEPTED = "ORDER_ACCEPTED"
STATUS_RECONCILED = "RECONCILED"
STATUS_BLOCKED = "BLOCKED"
STATUS_REJECTED = "REJECTED"
STATUS_UNCERTAIN = "UNCERTAIN"


@dataclass(frozen=True, slots=True)
class LiveOpenConfigV2:
    armed: bool = False


@dataclass(frozen=True, slots=True)
class LiveOpenCycleV2:
    armed: bool
    pending: int
    submitted: int
    reconciled: int
    blocked: int
    failed: int


def code_gate_enabled_v2() -> bool:
    return os.getenv(CODE_GATE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def load_live_open_config_v2() -> LiveOpenConfigV2:
    ensure_autotrader_schema_v2()
    with connect() as db:
        row = db.execute(
            "SELECT armed FROM pg_v2_autotrader_live_open_config WHERE config_id = 1"
        ).fetchone()
    if row is None:
        return LiveOpenConfigV2()
    value = row.get("armed") if isinstance(row, dict) else row[0]
    return LiveOpenConfigV2(armed=bool(value))


def save_live_open_config_v2(config: LiveOpenConfigV2) -> LiveOpenConfigV2:
    ensure_autotrader_schema_v2()
    with connect() as db:
        db.execute(
            """
            UPDATE pg_v2_autotrader_live_open_config
            SET armed = ?, updated_at = now()
            WHERE config_id = 1
            """,
            (bool(config.armed),),
        )
    return config


def _row_dict(row: Any) -> dict[str, Any]:
    return dict(row) if not isinstance(row, dict) else row


def _utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _candidate_open_requests() -> tuple[dict[str, Any], ...]:
    with connect() as db:
        rows = db.execute(
            """
            SELECT request_id, pilot_key, strategy_key, desired_direction,
                   signal_at, signal, account_id, uic, asset_type, market_id,
                   instrument_id, budget_amount, budget_currency, status, created_at
            FROM pg_v2_autotrader_execution_requests
            WHERE action = 'OPEN' AND status IN (?, ?)
            ORDER BY created_at ASC
            """,
            (STATUS_PENDING, STATUS_APPROVED),
        ).fetchall()
    return tuple(_row_dict(row) for row in rows)


def _entry_authority_changed_after_request(request: dict[str, Any]) -> bool:
    """Entry authority is prospective; mode/arming changes never revive old signals."""
    with connect() as db:
        row = db.execute(
            """
            SELECT updated_at
            FROM pg_v2_autotrader_strategy_enrollments
            WHERE pilot_key = ? AND enabled = TRUE
            """,
            (str(request["pilot_key"]),),
        ).fetchone()
    if row is None:
        return True
    updated_at = row.get("updated_at") if isinstance(row, dict) else row[0]
    return _utc(updated_at) > _utc(request["created_at"])


def load_open_requests_waiting_approval_v2(pilot_key: str) -> tuple[dict[str, Any], ...]:
    ensure_autotrader_schema_v2()
    enrollment = load_strategy_enrollment_v2(pilot_key)
    if (
        enrollment is None
        or not enrollment.enabled
        or enrollment.execution_mode != EXECUTION_MODE_LIVE
        or enrollment.entry_mode != ENTRY_MODE_APPROVAL_REQUIRED
    ):
        return ()
    with connect() as db:
        rows = db.execute(
            """
            SELECT request_id, pilot_key, strategy_key, desired_direction,
                   signal_at, signal, budget_amount, budget_currency, created_at
            FROM pg_v2_autotrader_execution_requests
            WHERE pilot_key = ? AND action = 'OPEN' AND status = ?
            ORDER BY created_at DESC
            """,
            (str(pilot_key), STATUS_PENDING),
        ).fetchall()
    requests = tuple(_row_dict(row) for row in rows)
    return tuple(item for item in requests if not _entry_authority_changed_after_request(item))


def approve_open_request_v2(
    *,
    pilot_key: str,
    request_id: str,
    source: str = "TRADINGDESK",
    now: datetime | None = None,
) -> dict[str, Any]:
    """One-shot approval for exactly one still-current OPEN request."""
    ensure_autotrader_schema_v2()
    enrollment = load_strategy_enrollment_v2(pilot_key)
    if enrollment is None or not enrollment.enabled:
        raise LookupError("active AutoManage pilot not found")
    if enrollment.execution_mode != EXECUTION_MODE_LIVE:
        raise ValueError("only a LIVE strategy can approve an OPEN request")
    if enrollment.entry_mode != ENTRY_MODE_APPROVAL_REQUIRED:
        raise ValueError("pilot is not configured for per-entry approval")
    if not enrollment.live_open_armed:
        raise ValueError("LIVE OPEN must be armed before a one-shot request can be approved")

    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        raise ValueError("approval time must be timezone-aware")
    current_time = current_time.astimezone(timezone.utc)

    with connect() as db:
        row = db.execute(
            """
            SELECT request_id, pilot_key, signal_at, status, created_at,
                   desired_direction, signal, budget_amount, budget_currency
            FROM pg_v2_autotrader_execution_requests
            WHERE request_id = ? AND pilot_key = ? AND action = 'OPEN'
            """,
            (str(request_id), str(pilot_key)),
        ).fetchone()
        if row is None:
            raise LookupError("OPEN request not found")
        item = _row_dict(row)
        if str(item["status"]) != STATUS_PENDING:
            raise ValueError("OPEN request is no longer waiting for approval")
        if _entry_authority_changed_after_request(item):
            raise ValueError("OPEN request predates the current entry authority")
        signal_at = _utc(item["signal_at"])
        age = current_time - signal_at
        if age < timedelta(0) or age > OPEN_SIGNAL_MAX_AGE:
            raise ValueError("OPEN request signal is stale")
        newer_signal = db.execute(
            """
            SELECT 1
            FROM pg_v2_autotrader_strategy_evaluations
            WHERE pilot_key = ? AND intent_id IS NOT NULL AND signal_at > ?
            LIMIT 1
            """,
            (str(pilot_key), signal_at),
        ).fetchone()
        if newer_signal is not None:
            raise ValueError("a newer strategy signal exists; approve the latest signal instead")
        db.execute(
            """
            UPDATE pg_v2_autotrader_execution_requests
            SET status = ?, approved_at = ?, approval_source = ?,
                block_reason = NULL, updated_at = now()
            WHERE request_id = ? AND pilot_key = ? AND status = ?
            """,
            (
                STATUS_APPROVED,
                current_time,
                str(source or "TRADINGDESK"),
                str(request_id),
                str(pilot_key),
                STATUS_PENDING,
            ),
        )
    item["status"] = STATUS_APPROVED
    item["approved_at"] = current_time
    item["approval_source"] = str(source or "TRADINGDESK")
    return item


def _update_request(
    request_id: str,
    *,
    status: str,
    block_reason: str | None = None,
    order_id: str | None = None,
) -> None:
    with connect() as db:
        db.execute(
            """
            UPDATE pg_v2_autotrader_execution_requests
            SET status = ?, block_reason = ?, order_id = COALESCE(?, order_id), updated_at = now()
            WHERE request_id = ?
            """,
            (status, block_reason, order_id, str(request_id)),
        )


def _newer_strategy_request_exists(request: dict[str, Any]) -> bool:
    """Treat any later MACD cross as authoritative, even when it plans HOLD."""
    with connect() as db:
        row = db.execute(
            """
            SELECT 1
            FROM pg_v2_autotrader_strategy_evaluations
            WHERE pilot_key = ? AND intent_id IS NOT NULL AND signal_at > ?
            LIMIT 1
            """,
            (str(request["pilot_key"]), request["signal_at"]),
        ).fetchone()
    return row is not None


def _account_info(client, account_id: str) -> tuple[str, str]:
    payload = client._get("port/v1/accounts/me")
    rows = payload.get("Data") or []
    if not isinstance(rows, list):
        raise RuntimeError("Saxo account list had invalid format")
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("AccountId") or "") != str(account_id):
            continue
        if not bool(row.get("Active", True)):
            raise RuntimeError("AutoManage account is not active")
        key = str(row.get("AccountKey") or "").strip()
        currency = str(row.get("Currency") or "").strip().upper()
        if not key or not currency:
            raise RuntimeError("Saxo account is missing AccountKey/Currency")
        return key, currency
    raise RuntimeError("could not resolve Saxo account for AutoManage entry")


def _product_positions(
    observations: tuple[PositionObservationV2, ...],
    *,
    account_id: str,
    uic: int,
    asset_type: str,
) -> tuple[PositionObservationV2, ...]:
    return tuple(
        item
        for item in observations
        if item.account_id == str(account_id)
        and int(item.uic) == int(uic)
        and item.asset_type == str(asset_type)
    )


def _direction_of(observation: PositionObservationV2) -> str:
    side = observation.direction.strip().lower()
    if side == "buy":
        return "LONG"
    if side == "sell":
        return "SHORT"
    raise RuntimeError(f"unsupported Saxo position direction: {observation.direction}")


def _open_orders_exist(client, *, account_key: str, uic: int) -> bool:
    payload = client._get("port/v1/orders/me", params={"$top": 1000})
    rows = payload.get("Data") or []
    if not isinstance(rows, list):
        raise RuntimeError("Saxo open-order list had invalid format")
    return any(
        isinstance(row, dict)
        and str(row.get("AccountKey") or "") == str(account_key)
        and int(row.get("Uic") or -1) == int(uic)
        for row in rows
    )


def _settled_close_provenance(pilot_key: str) -> tuple[bool, bool]:
    """Return (settled_close_exists, unresolved_close_exists) since latest enrollment."""
    with connect() as db:
        enrollment = db.execute(
            """
            SELECT account_id, uic, asset_type, enrolled_at
            FROM pg_v2_autotrader_strategy_enrollments
            WHERE pilot_key = ? AND enabled = TRUE
            """,
            (str(pilot_key),),
        ).fetchone()
        if enrollment is None:
            return False, True
        item = _row_dict(enrollment)
        settled = db.execute(
            """
            SELECT 1
            FROM pg_v2_autotrader_live_close_attempts AS close
            JOIN pg_v2_autotrader_equity_reconciliations AS rec
              ON rec.close_event_id = close.event_id
            WHERE close.account_id = ? AND close.uic = ? AND close.asset_type = ?
              AND close.created_at >= ? AND close.status = 'RECONCILED'
            ORDER BY close.created_at DESC
            LIMIT 1
            """,
            (str(item["account_id"]), int(item["uic"]), str(item["asset_type"]), item["enrolled_at"]),
        ).fetchone()
        unresolved = db.execute(
            """
            SELECT 1
            FROM pg_v2_autotrader_live_close_attempts AS close
            LEFT JOIN pg_v2_autotrader_equity_reconciliations AS rec
              ON rec.close_event_id = close.event_id
            WHERE close.account_id = ? AND close.uic = ? AND close.asset_type = ?
              AND close.created_at >= ?
              AND close.status IN ('SUBMITTING', 'ORDER_ACCEPTED', 'RECONCILED', 'UNCERTAIN')
              AND rec.close_event_id IS NULL
            ORDER BY close.created_at DESC
            LIMIT 1
            """,
            (str(item["account_id"]), int(item["uic"]), str(item["asset_type"]), item["enrolled_at"]),
        ).fetchone()
    return settled is not None, unresolved is not None


def _record_attempt_before_submit(
    *,
    request: dict[str, Any],
    amount: float,
    budget_amount: float,
    account_currency: str,
    buy_sell: str,
    external_reference: str,
    precheck,
) -> bool:
    with connect() as db:
        existing = db.execute(
            "SELECT status FROM pg_v2_autotrader_live_open_attempts WHERE request_id = ?",
            (str(request["request_id"]),),
        ).fetchone()
        if existing is not None:
            return False
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_live_open_attempts(
                request_id, account_id, uic, asset_type, desired_direction,
                buy_sell, amount, budget_amount, currency, external_reference,
                status, precheck_result, precheck_initial_margin,
                precheck_notional, precheck_cost
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(request["request_id"]),
                str(request["account_id"]),
                int(request["uic"]),
                str(request["asset_type"]),
                str(request["desired_direction"]),
                str(buy_sell),
                float(amount),
                float(budget_amount),
                account_currency,
                external_reference,
                STATUS_SUBMITTING,
                precheck.precheck_result,
                precheck.initial_margin_account,
                precheck.notional_account,
                precheck.estimated_cost_account,
            ),
        )
    return True


def _update_attempt(
    request_id: str,
    *,
    status: str,
    order_id: str | None = None,
    error: str | None = None,
) -> None:
    with connect() as db:
        db.execute(
            """
            UPDATE pg_v2_autotrader_live_open_attempts
            SET status = ?, order_id = COALESCE(?, order_id),
                error_message = ?, updated_at = now()
            WHERE request_id = ?
            """,
            (status, order_id, error, str(request_id)),
        )


def _accepted_attempts() -> tuple[dict[str, Any], ...]:
    with connect() as db:
        rows = db.execute(
            """
            SELECT request_id, account_id, uic, asset_type, desired_direction,
                   amount, order_id
            FROM pg_v2_autotrader_live_open_attempts
            WHERE status = ?
            ORDER BY updated_at ASC
            """,
            (STATUS_ORDER_ACCEPTED,),
        ).fetchall()
    return tuple(_row_dict(row) for row in rows)


def _rotate_managed_basis_and_anchor(request_id: str, observation: PositionObservationV2) -> None:
    with connect() as db:
        request = db.execute(
            "SELECT pilot_key FROM pg_v2_autotrader_execution_requests WHERE request_id = ?",
            (str(request_id),),
        ).fetchone()
        if request is None:
            raise RuntimeError("OPEN request disappeared during reconciliation")
        pilot_key = str(request.get("pilot_key") if isinstance(request, dict) else request[0])
        db.execute(
            """
            UPDATE pg_v2_autotrader_managed_positions
            SET managed = FALSE, updated_at = now()
            WHERE account_id = ? AND uic = ? AND asset_type = ?
            """,
            (observation.account_id, int(observation.uic), observation.asset_type),
        )
        db.execute(
            """
            UPDATE pg_v2_autotrader_strategy_enrollments
            SET anchor_net_position_id = ?, updated_at = now()
            WHERE pilot_key = ? AND enabled = TRUE
            """,
            (observation.net_position_id, pilot_key),
        )
    enroll_position_v1(observation)


def reconcile_live_open_attempts_v2(client) -> int:
    attempts = _accepted_attempts()
    if not attempts:
        return 0
    observations = _position_observations_v2(client)
    reconciled = 0
    for attempt in attempts:
        matches = _product_positions(
            observations,
            account_id=str(attempt["account_id"]),
            uic=int(attempt["uic"]),
            asset_type=str(attempt["asset_type"]),
        )
        if len(matches) != 1:
            continue
        current = matches[0]
        if _direction_of(current) != str(attempt["desired_direction"]):
            continue
        if abs(float(current.amount) - float(attempt["amount"])) > 1e-9:
            continue
        request_id = str(attempt["request_id"])
        _rotate_managed_basis_and_anchor(request_id, current)
        _update_attempt(request_id, status=STATUS_RECONCILED)
        _update_request(
            request_id,
            status=STATUS_RECONCILED,
            order_id=None if attempt.get("order_id") is None else str(attempt["order_id"]),
        )
        reconciled += 1
    return reconciled


def run_live_open_cycle_v2() -> LiveOpenCycleV2:
    if not using_postgres():
        return LiveOpenCycleV2(False, 0, 0, 0, 0, 0)
    ensure_autotrader_schema_v2()
    config = load_live_open_config_v2()
    armed = bool(config.armed and code_gate_enabled_v2())
    candidates = _candidate_open_requests()

    # Reconciliation is a safety duty, not new order authority. If a prior POST was
    # already accepted, keep adopting the exact Saxo position into managed state
    # even after the user or deployment disarms future OPEN submissions.
    client = None
    reconciled = 0
    if _accepted_attempts():
        client = _require_live_client()
        reconciled = reconcile_live_open_attempts_v2(client)

    if not armed:
        return LiveOpenCycleV2(False, len(candidates), 0, reconciled, 0, 0)

    if client is None:
        client = _require_live_client()
    if _position_netting_mode(client).lower() != "intraday":
        LOGGER.error("LIVE OPEN blocked: Saxo PositionNettingMode must be Intraday")
        return LiveOpenCycleV2(True, len(candidates), 0, reconciled, 1, 0)

    candidates = _candidate_open_requests()
    if not candidates:
        return LiveOpenCycleV2(True, 0, 0, reconciled, 0, 0)

    observations = _position_observations_v2(client)
    submitted = 0
    blocked = 0
    failed = 0
    now = datetime.now(timezone.utc)

    for request in candidates:
        request_id = str(request["request_id"])
        try:
            enrollment = load_strategy_enrollment_v2(str(request["pilot_key"]))
            if (
                enrollment is None
                or not enrollment.enabled
                or enrollment.execution_mode != EXECUTION_MODE_LIVE
                or enrollment.strategy_key != str(request["strategy_key"])
                or enrollment.account_id != str(request["account_id"])
                or int(enrollment.uic) != int(request["uic"])
                or enrollment.asset_type != str(request["asset_type"])
                or enrollment.market_id != int(request["market_id"])
                or enrollment.instrument_id != int(request["instrument_id"])
            ):
                _update_request(request_id, status=STATUS_BLOCKED, block_reason="LIVE_ENTRY_ENROLLMENT_MISMATCH")
                blocked += 1
                continue

            request_status = str(request["status"])
            if enrollment.entry_mode == ENTRY_MODE_MANUAL_ONLY:
                if request_status == STATUS_APPROVED:
                    _update_request(request_id, status=STATUS_BLOCKED, block_reason="ENTRY_MODE_MANUAL_ONLY")
                    blocked += 1
                continue
            if not enrollment.live_open_armed:
                continue
            if enrollment.entry_mode == ENTRY_MODE_APPROVAL_REQUIRED and request_status != STATUS_APPROVED:
                continue
            if enrollment.entry_mode == ENTRY_MODE_AUTO and request_status not in {STATUS_PENDING, STATUS_APPROVED}:
                continue

            if _entry_authority_changed_after_request(request):
                _update_request(
                    request_id,
                    status=STATUS_SUPERSEDED,
                    block_reason="ENTRY_AUTHORITY_CHANGED",
                )
                blocked += 1
                continue

            if _newer_strategy_request_exists(request):
                _update_request(
                    request_id,
                    status=STATUS_SUPERSEDED,
                    block_reason="NEWER_STRATEGY_SIGNAL",
                )
                blocked += 1
                continue

            signal_at = _utc(request["signal_at"])
            age = now - signal_at
            if age < timedelta(0) or age > OPEN_SIGNAL_MAX_AGE:
                _update_request(request_id, status=STATUS_BLOCKED, block_reason="STALE_ENTRY_SIGNAL")
                blocked += 1
                continue

            positions = _product_positions(
                observations,
                account_id=enrollment.account_id,
                uic=enrollment.uic,
                asset_type=enrollment.asset_type,
            )
            if positions:
                _update_request(request_id, status=STATUS_BLOCKED, block_reason="PRODUCT_NOT_CONFIRMED_FLAT")
                blocked += 1
                continue

            settled_close, unresolved_close = _settled_close_provenance(enrollment.pilot_key)
            if unresolved_close:
                continue
            if not settled_close:
                _update_request(request_id, status=STATUS_BLOCKED, block_reason="FLAT_WITHOUT_SETTLED_PG_CLOSE")
                blocked += 1
                continue

            account_key, account_currency = _account_info(client, enrollment.account_id)
            if _open_orders_exist(client, account_key=account_key, uic=enrollment.uic):
                continue

            equity = load_pilot_equity_v2(pilot_key=enrollment.pilot_key)
            if equity.currency.upper() != account_currency.upper():
                _update_request(request_id, status=STATUS_BLOCKED, block_reason="PILOT_ACCOUNT_CURRENCY_MISMATCH")
                blocked += 1
                continue
            budget = float(equity.entry_budget)
            if budget <= 0:
                _update_request(request_id, status=STATUS_BLOCKED, block_reason="PILOT_EQUITY_EXHAUSTED")
                blocked += 1
                continue

            _, _, envelope = require_entry_policy_v2(
                enrollment,
                direction=str(request["desired_direction"]),
                currency=account_currency,
                controlled_capital=budget,
            )
            instrument = SaxoInstrument(
                asset=enrollment.market_name,
                uic=enrollment.uic,
                asset_type=enrollment.asset_type,
            )
            sizing = find_largest_legal_entry_v2(
                client,
                account_key=account_key,
                account_currency=account_currency,
                instrument=instrument,
                direction=str(request["desired_direction"]),
                envelope=envelope,
                controlled_capital=budget,
                external_reference_prefix=f"pg-size-{request_id.replace('-', '')[:24]}",
            )

            final = precheck_entry_amount_v2(
                client,
                account_key=account_key,
                account_currency=account_currency,
                instrument=instrument,
                rules=sizing.rules,
                direction=str(request["desired_direction"]),
                amount=sizing.amount,
                envelope=envelope,
                controlled_capital=budget,
                external_reference=f"pg-final-{request_id.replace('-', '')[:28]}",
            )
            if not final.allowed:
                _update_request(
                    request_id,
                    status=STATUS_BLOCKED,
                    block_reason="FINAL_PRECHECK_OR_MARGIN_ENVELOPE_BLOCKED",
                )
                blocked += 1
                continue

            external_reference = f"pg-open-{request_id.replace('-', '')[:32]}"
            order_payload = live_open_order_payload_v2(
                account_key=account_key,
                instrument=instrument,
                amount=sizing.amount,
                direction=str(request["desired_direction"]),
                external_reference=external_reference,
            )
            if not _record_attempt_before_submit(
                request=request,
                amount=sizing.amount,
                budget_amount=budget,
                account_currency=account_currency,
                buy_sell=final.buy_sell,
                external_reference=external_reference,
                precheck=final,
            ):
                continue
            _update_request(request_id, status=STATUS_SUBMITTING)

            try:
                response = _post_once(client, "trade/v2/orders", order_payload)
            except SaxoError as exc:
                uncertain = str(getattr(exc, "status", "")).upper() in {
                    "TIMEOUT",
                    "CONNECTION_FAILED",
                    "REQUEST_FAILED",
                    "INVALID_RESPONSE",
                }
                status = STATUS_UNCERTAIN if uncertain else STATUS_REJECTED
                _update_attempt(request_id, status=status, error=str(exc))
                _update_request(request_id, status=status, block_reason=str(exc))
                if uncertain:
                    LOGGER.error("LIVE OPEN uncertain request=%s; blind retry blocked", request_id)
                else:
                    LOGGER.warning("LIVE OPEN rejected request=%s: %s", request_id, exc)
                failed += 1
                continue

            order_value = response.get("OrderId") or response.get("OrderIds")
            if isinstance(order_value, list):
                order_id = str(order_value[0]) if order_value else None
            else:
                order_id = None if order_value is None else str(order_value)
            _update_attempt(request_id, status=STATUS_ORDER_ACCEPTED, order_id=order_id)
            _update_request(request_id, status=STATUS_ORDER_ACCEPTED, order_id=order_id)
            submitted += 1
        except (ValueError, EntrySizingError) as exc:
            _update_request(request_id, status=STATUS_BLOCKED, block_reason=str(exc))
            LOGGER.warning("LIVE OPEN blocked request=%s: %s", request_id, exc)
            blocked += 1
        except Exception as exc:
            LOGGER.warning("LIVE OPEN cycle failed request=%s: %s", request_id, exc, exc_info=True)
            failed += 1

    return LiveOpenCycleV2(True, len(candidates), submitted, reconciled, blocked, failed)


def run_live_open_forever_v2(*, interval_seconds: int = 2) -> None:
    interval = max(1, int(interval_seconds))
    while True:
        started = time.monotonic()
        try:
            run_live_open_cycle_v2()
        except Exception as exc:
            LOGGER.warning("LIVE OPEN cycle failed: %s", exc, exc_info=True)
        sleep_to_fixed_start_cadence_v2(started, interval)


__all__ = [
    "CODE_GATE_ENV",
    "LiveOpenConfigV2",
    "LiveOpenCycleV2",
    "OPEN_SIGNAL_MAX_AGE",
    "STATUS_APPROVED",
    "approve_open_request_v2",
    "code_gate_enabled_v2",
    "load_live_open_config_v2",
    "load_open_requests_waiting_approval_v2",
    "reconcile_live_open_attempts_v2",
    "run_live_open_cycle_v2",
    "run_live_open_forever_v2",
    "save_live_open_config_v2",
]
