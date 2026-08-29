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
    _account_key_for_account_id,
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
    EXECUTION_MODE_LIVE,
    load_strategy_enrollment_v2,
)
from database import connect, using_postgres
from saxo_provider import SaxoError, SaxoInstrument


LOGGER = logging.getLogger("pricegauger.autotrader.live_open_v2")
CODE_GATE_ENV = "PRICEGAUGER_AUTOTRADER_LIVE_OPEN_CODE_ENABLED"
OPEN_SIGNAL_MAX_AGE = timedelta(minutes=90)

STATUS_PENDING = "PENDING"
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


def _pending_open_requests() -> tuple[dict[str, Any], ...]:
    with connect() as db:
        rows = db.execute(
            """
            SELECT request_id, pilot_key, strategy_key, desired_direction,
                   signal_at, signal, account_id, uic, asset_type, market_id,
                   instrument_id, budget_amount, budget_currency
            FROM pg_v2_autotrader_execution_requests
            WHERE action = 'OPEN' AND status = ?
            ORDER BY created_at ASC
            """,
            (STATUS_PENDING,),
        ).fetchall()
    return tuple(_row_dict(row) for row in rows)


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


def _record_attempt_before_submit(
    *,
    request: dict[str, Any],
    amount: float,
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
                float(request["budget_amount"]),
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
        _update_request(request_id, status=STATUS_RECONCILED, order_id=None if attempt.get("order_id") is None else str(attempt["order_id"]))
        reconciled += 1
    return reconciled


def run_live_open_cycle_v2() -> LiveOpenCycleV2:
    if not using_postgres():
        return LiveOpenCycleV2(False, 0, 0, 0, 0, 0)
    ensure_autotrader_schema_v2()
    config = load_live_open_config_v2()
    armed = bool(config.armed and code_gate_enabled_v2())
    pending = _pending_open_requests()
    if not armed:
        return LiveOpenCycleV2(False, len(pending), 0, 0, 0, 0)

    client = _require_live_client()
    if _position_netting_mode(client).lower() != "intraday":
        LOGGER.error("LIVE OPEN blocked: Saxo PositionNettingMode must be Intraday")
        return LiveOpenCycleV2(True, len(pending), 0, 0, 1, 0)

    reconciled = reconcile_live_open_attempts_v2(client)
    pending = _pending_open_requests()
    if not pending:
        return LiveOpenCycleV2(True, 0, 0, reconciled, 0, 0)

    observations = _position_observations_v2(client)
    submitted = 0
    blocked = 0
    failed = 0
    now = datetime.now(timezone.utc)

    for request in pending:
        request_id = str(request["request_id"])
        try:
            enrollment = load_strategy_enrollment_v2(str(request["pilot_key"]))
            if (
                enrollment is None
                or not enrollment.enabled
                or enrollment.execution_mode != EXECUTION_MODE_LIVE
                or not enrollment.live_open_armed
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

            account_key, account_currency = _account_info(client, enrollment.account_id)
            if _open_orders_exist(client, account_key=account_key, uic=enrollment.uic):
                # A still-open Saxo order is not a safe flat execution basis.
                continue

            equity = load_pilot_equity_v2(pilot_key=enrollment.pilot_key)
            if equity.currency.upper() != account_currency.upper():
                _update_request(request_id, status=STATUS_BLOCKED, block_reason="PILOT_ACCOUNT_CURRENCY_MISMATCH")
                blocked += 1
                continue
            budget = min(float(request["budget_amount"]), float(equity.entry_budget))
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

            # Final execution precheck is deliberately repeated after sizing so no
            # cached proposal can authorize a real order.
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
                account_currency=account_currency,
                buy_sell=final.buy_sell,
                external_reference=external_reference,
                precheck=final,
            ):
                # An attempt already crossed the durable idempotency boundary.
                # Never repeat POST based on the strategy request alone.
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

    return LiveOpenCycleV2(True, len(pending), submitted, reconciled, blocked, failed)


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
    "code_gate_enabled_v2",
    "load_live_open_config_v2",
    "reconcile_live_open_attempts_v2",
    "run_live_open_cycle_v2",
    "run_live_open_forever_v2",
    "save_live_open_config_v2",
]
