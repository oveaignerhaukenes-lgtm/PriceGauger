from __future__ import annotations

from dataclasses import dataclass
import logging
import time
from typing import Any

from autotrader_cadence_v2 import sleep_to_fixed_start_cadence_v2
from autotrader_live_close_v1 import (
    STATUS_ORDER_ACCEPTED,
    STATUS_RECONCILED,
    STATUS_REJECTED,
    STATUS_SUBMITTING,
    STATUS_UNCERTAIN,
    _account_key_for_account_id,
    _close_payload,
    _post_once,
    _position_netting_mode,
    _precheck_is_clear,
    _record_attempt_before_submit,
    _reconcile_accepted_attempts,
    _require_live_client,
    _update_attempt,
    code_gate_enabled_v1,
    load_live_close_config_v1,
)
from autotrader_managed_positions_v1 import is_position_managed_v1
from autotrader_risk_control_v2 import PositionObservationV2, _position_observations_v2
from autotrader_schema_v2 import ensure_autotrader_schema_v2
from autotrader_strategy_enrollment_v2 import (
    EXECUTION_MODE_LIVE,
    load_strategy_enrollment_v2,
)
from database import connect, using_postgres
from saxo_provider import SaxoError


LOGGER = logging.getLogger("pricegauger.autotrader.strategy_live_close_v2")
REQUEST_PENDING = "PENDING"
REQUEST_SUBMITTING = "SUBMITTING"
REQUEST_ORDER_ACCEPTED = "ORDER_ACCEPTED"
REQUEST_RECONCILED = "RECONCILED"
REQUEST_BLOCKED = "BLOCKED"
REQUEST_REJECTED = "REJECTED"
REQUEST_UNCERTAIN = "UNCERTAIN"


@dataclass(frozen=True, slots=True)
class StrategyCloseCycleV2:
    armed: bool
    pending: int
    submitted: int
    reconciled: int
    blocked: int
    failed: int


def _record_dict(row: Any) -> dict[str, Any]:
    return dict(row) if not isinstance(row, dict) else row


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
            (status, block_reason, order_id, request_id),
        )


def _sync_close_attempt_statuses() -> int:
    with connect() as db:
        rows = db.execute(
            """
            SELECT req.request_id, close.status, close.order_id, close.error_message
            FROM pg_v2_autotrader_execution_requests AS req
            JOIN pg_v2_autotrader_live_close_attempts AS close
              ON close.event_id = req.request_id
            WHERE req.action = 'CLOSE'
              AND req.status IN ('SUBMITTING', 'ORDER_ACCEPTED', 'UNCERTAIN')
            """
        ).fetchall()
    reconciled = 0
    for row in rows:
        item = _record_dict(row)
        close_status = str(item["status"])
        mapped = {
            STATUS_SUBMITTING: REQUEST_SUBMITTING,
            STATUS_ORDER_ACCEPTED: REQUEST_ORDER_ACCEPTED,
            STATUS_RECONCILED: REQUEST_RECONCILED,
            STATUS_REJECTED: REQUEST_REJECTED,
            STATUS_UNCERTAIN: REQUEST_UNCERTAIN,
        }.get(close_status)
        if mapped is None:
            continue
        _update_request(
            str(item["request_id"]),
            status=mapped,
            block_reason=None if mapped != REQUEST_REJECTED else str(item.get("error_message") or "SAXO_REJECTED"),
            order_id=None if item.get("order_id") is None else str(item["order_id"]),
        )
        if mapped == REQUEST_RECONCILED:
            reconciled += 1
    return reconciled


def _pending_close_requests() -> tuple[dict[str, Any], ...]:
    with connect() as db:
        rows = db.execute(
            """
            SELECT request_id, evaluation_id, pilot_key, strategy_key, desired_direction,
                   signal_at, account_id, observed_net_position_id, observed_direction,
                   observed_amount, observed_average_open_price, uic, asset_type
            FROM pg_v2_autotrader_execution_requests
            WHERE action = 'CLOSE' AND status = ?
            ORDER BY created_at ASC
            """,
            (REQUEST_PENDING,),
        ).fetchall()
    return tuple(_record_dict(row) for row in rows)


def _matching_current_position(
    request: dict[str, Any],
    observations: tuple[PositionObservationV2, ...],
) -> PositionObservationV2 | None:
    matches = tuple(
        item
        for item in observations
        if item.account_id == str(request["account_id"])
        and int(item.uic) == int(request["uic"])
        and item.asset_type == str(request["asset_type"])
    )
    if len(matches) > 1:
        raise RuntimeError("multiple live positions match one strategy CLOSE product")
    return matches[0] if matches else None


def _basis_is_unchanged(request: dict[str, Any], current: PositionObservationV2) -> bool:
    expected_position_id = request.get("observed_net_position_id")
    if expected_position_id and str(expected_position_id) != current.net_position_id:
        return False
    expected_direction = str(request.get("observed_direction") or "").upper()
    current_direction = "LONG" if current.direction.strip().lower() == "buy" else "SHORT"
    if expected_direction and expected_direction != current_direction:
        return False
    expected_amount = request.get("observed_amount")
    if expected_amount is None or abs(float(expected_amount) - float(current.amount)) > 1e-12:
        return False
    expected_open = request.get("observed_average_open_price")
    if expected_open is None or abs(float(expected_open) - float(current.average_open_price)) > 1e-12:
        return False
    return True


def run_strategy_live_close_cycle_v2() -> StrategyCloseCycleV2:
    if not using_postgres():
        return StrategyCloseCycleV2(False, 0, 0, 0, 0, 0)
    ensure_autotrader_schema_v2()

    config = load_live_close_config_v1()
    armed = bool(config.armed and code_gate_enabled_v1())
    if not armed:
        # Keep requests pending while the independent system-wide execution kill
        # switch is off. Enrollment alone must never bypass this gate.
        return StrategyCloseCycleV2(False, len(_pending_close_requests()), 0, 0, 0, 0)

    client = _require_live_client()
    if _position_netting_mode(client).lower() != "intraday":
        LOGGER.error("strategy LIVE close blocked: Saxo PositionNettingMode must be Intraday")
        return StrategyCloseCycleV2(True, len(_pending_close_requests()), 0, 0, 1, 0)

    # Reuse the proven close reconciliation before considering another POST.
    _reconcile_accepted_attempts(client)
    reconciled = _sync_close_attempt_statuses()
    pending = _pending_close_requests()
    if not pending:
        return StrategyCloseCycleV2(True, 0, 0, reconciled, 0, 0)

    observations = _position_observations_v2(client)
    submitted = 0
    blocked = 0
    failed = 0

    for request in pending:
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
            ):
                _update_request(request_id, status=REQUEST_BLOCKED, block_reason="LIVE_ENROLLMENT_MISMATCH")
                blocked += 1
                continue

            current = _matching_current_position(request, observations)
            if current is None:
                # Desired CLOSE state already exists, but because no PriceGauger
                # close was submitted there is deliberately no authoritative P/L
                # booking for this request.
                _update_request(request_id, status=REQUEST_RECONCILED, block_reason="ALREADY_FLAT_NO_ORDER")
                reconciled += 1
                continue
            if not is_position_managed_v1(current):
                _update_request(request_id, status=REQUEST_BLOCKED, block_reason="POSITION_NOT_EXACTLY_MANAGED")
                blocked += 1
                continue
            if not _basis_is_unchanged(request, current):
                _update_request(request_id, status=REQUEST_BLOCKED, block_reason="STALE_POSITION_BASIS")
                blocked += 1
                continue
            if not current.can_be_closed or not current.is_market_open or current.non_tradable_reason not in {"", "None", "NONE", None}:
                # Market/tradability can recover. Do not permanently consume the
                # request; leave it pending rather than turning a temporary closure
                # into a new signal requirement.
                continue

            account_key = _account_key_for_account_id(client, current.account_id)
            external_reference = f"pg-strategy-close-{request_id.replace('-', '')[:30]}"
            payload = _close_payload(
                account_key=account_key,
                observation=current,
                external_reference=external_reference,
            )
            precheck = _post_once(client, "trade/v2/orders/precheck", payload)
            if not _precheck_is_clear(precheck):
                reason = str(precheck.get("PreCheckResult") or "PRECHECK_BLOCKED")
                if precheck.get("PreTradeDisclaimers"):
                    reason += ":DISCLAIMERS"
                _update_request(request_id, status=REQUEST_BLOCKED, block_reason=reason)
                blocked += 1
                continue

            if not _record_attempt_before_submit(
                event_id=request_id,
                observation=current,
                close_side=str(payload["BuySell"]),
                external_reference=external_reference,
                precheck_result=str(precheck.get("PreCheckResult") or ""),
            ):
                # Existing attempt means execution has already crossed the durable
                # idempotency boundary. Never issue another POST.
                _sync_close_attempt_statuses()
                continue

            _update_request(request_id, status=REQUEST_SUBMITTING)
            try:
                response = _post_once(client, "trade/v2/orders", payload)
            except SaxoError as exc:
                uncertain = str(getattr(exc, "status", "")).upper() in {
                    "TIMEOUT",
                    "CONNECTION_FAILED",
                    "REQUEST_FAILED",
                    "INVALID_RESPONSE",
                }
                attempt_status = STATUS_UNCERTAIN if uncertain else STATUS_REJECTED
                request_status = REQUEST_UNCERTAIN if uncertain else REQUEST_REJECTED
                _update_attempt(request_id, status=attempt_status, error=str(exc))
                _update_request(request_id, status=request_status, block_reason=str(exc))
                if uncertain:
                    LOGGER.error("strategy close submission uncertain request=%s; blind retry blocked", request_id)
                else:
                    LOGGER.warning("strategy close rejected request=%s: %s", request_id, exc)
                failed += 1
                continue

            order_value = response.get("OrderId") or response.get("OrderIds")
            if isinstance(order_value, list):
                order_id = str(order_value[0]) if order_value else None
            else:
                order_id = None if order_value is None else str(order_value)
            _update_attempt(request_id, status=STATUS_ORDER_ACCEPTED, order_id=order_id)
            _update_request(request_id, status=REQUEST_ORDER_ACCEPTED, order_id=order_id)
            submitted += 1
        except Exception as exc:
            LOGGER.warning("strategy LIVE close failed request=%s: %s", request_id, exc, exc_info=True)
            failed += 1

    return StrategyCloseCycleV2(True, len(pending), submitted, reconciled, blocked, failed)


def run_strategy_live_close_forever_v2(*, interval_seconds: int = 2) -> None:
    interval = max(1, int(interval_seconds))
    while True:
        started = time.monotonic()
        try:
            run_strategy_live_close_cycle_v2()
        except Exception as exc:
            LOGGER.warning("strategy LIVE close cycle failed: %s", exc, exc_info=True)
        sleep_to_fixed_start_cadence_v2(started, interval)


__all__ = [
    "StrategyCloseCycleV2",
    "run_strategy_live_close_cycle_v2",
    "run_strategy_live_close_forever_v2",
]
