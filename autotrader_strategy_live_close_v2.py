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
from autotrader_macd_binary_execution_v1 import is_simple_binary_macd_strategy_v1
from autotrader_managed_positions_v1 import is_position_managed_v1
from autotrader_manual_entry_adoption_v2 import run_manual_entry_adoption_cycle_v2
from autotrader_precheck_diagnostics_v1 import precheck_failure_diagnostics_v1
from autotrader_risk_control_v2 import PositionObservationV2, _position_observations_v2
from autotrader_schema_v2 import ensure_autotrader_schema_v2
from autotrader_strategy_enrollment_v2 import EXECUTION_MODE_LIVE, load_strategy_enrollment_v2
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


def _update_request(request_id: str, *, status: str, block_reason: str | None = None, order_id: str | None = None) -> None:
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
            JOIN pg_v2_autotrader_live_close_attempts AS close ON close.event_id = req.request_id
            WHERE req.action = 'CLOSE' AND req.status IN ('SUBMITTING', 'ORDER_ACCEPTED', 'UNCERTAIN')
            """
        ).fetchall()
    reconciled = 0
    for row in rows:
        item = _record_dict(row)
        mapped = {
            STATUS_SUBMITTING: REQUEST_SUBMITTING,
            STATUS_ORDER_ACCEPTED: REQUEST_ORDER_ACCEPTED,
            STATUS_RECONCILED: REQUEST_RECONCILED,
            STATUS_REJECTED: REQUEST_REJECTED,
            STATUS_UNCERTAIN: REQUEST_UNCERTAIN,
        }.get(str(item["status"]))
        if mapped is None:
            continue
        _update_request(
            str(item["request_id"]), status=mapped,
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
                   observed_amount, observed_average_open_price, uic, asset_type,
                   created_at, updated_at
            FROM pg_v2_autotrader_execution_requests
            WHERE action = 'CLOSE' AND status = ?
            ORDER BY created_at ASC
            """, (REQUEST_PENDING,),
        ).fetchall()
    return tuple(_record_dict(row) for row in rows)


def _pending_age_seconds(request: dict[str, Any]) -> float | None:
    value = request.get("created_at")
    if value is None:
        return None
    try:
        from datetime import datetime, timezone
        created = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - created.astimezone(timezone.utc)).total_seconds())
    except (TypeError, ValueError):
        return None


def _log_pending_close_health(pending: tuple[dict[str, Any], ...], *, config_armed: bool, code_gate: bool) -> None:
    if not pending:
        return
    oldest = pending[0]
    age = _pending_age_seconds(oldest)
    log = LOGGER.warning if age is None or age >= 10.0 or not (config_armed and code_gate) else LOGGER.info
    log(
        "strategy CLOSE pending health pending=%d config_armed=%s code_gate=%s effective_armed=%s oldest_request=%s oldest_age_seconds=%s",
        len(pending), config_armed, code_gate, bool(config_armed and code_gate),
        oldest.get("request_id"), "unknown" if age is None else f"{age:.1f}",
    )


def _matching_current_position(request: dict[str, Any], observations: tuple[PositionObservationV2, ...]) -> PositionObservationV2 | None:
    matches = tuple(item for item in observations if item.account_id == str(request["account_id"]) and int(item.uic) == int(request["uic"]) and item.asset_type == str(request["asset_type"]))
    if len(matches) > 1:
        raise RuntimeError("multiple live positions match one strategy CLOSE product")
    return matches[0] if matches else None


def _direction_v2(current: PositionObservationV2) -> str:
    return "LONG" if current.direction.strip().lower() == "buy" else "SHORT"


def _basis_is_unchanged(request: dict[str, Any], current: PositionObservationV2) -> bool:
    expected_position_id = request.get("observed_net_position_id")
    if expected_position_id and str(expected_position_id) != current.net_position_id:
        return False
    expected_direction = str(request.get("observed_direction") or "").upper()
    if expected_direction and expected_direction != _direction_v2(current):
        return False
    expected_amount = request.get("observed_amount")
    if expected_amount is None or abs(float(expected_amount) - float(current.amount)) > 1e-12:
        return False
    expected_open = request.get("observed_average_open_price")
    return expected_open is not None and abs(float(expected_open) - float(current.average_open_price)) <= 1e-12


def _binary_macd_rebase_is_safe(request: dict[str, Any], current: PositionObservationV2) -> bool:
    if not is_simple_binary_macd_strategy_v1(str(request.get("strategy_key") or "")):
        return False
    expected_position_id = str(request.get("observed_net_position_id") or "")
    if not expected_position_id or expected_position_id != str(current.net_position_id):
        return False
    expected_direction = str(request.get("observed_direction") or "").upper()
    return bool(expected_direction and expected_direction == _direction_v2(current))


def _binary_macd_managed_identity_is_authorized(request: dict[str, Any], current: PositionObservationV2) -> bool:
    if not _binary_macd_rebase_is_safe(request, current):
        return False
    with connect() as db:
        row = db.execute(
            """
            SELECT direction FROM pg_v2_autotrader_managed_positions
            WHERE account_id = ? AND net_position_id = ? AND uic = ? AND asset_type = ? AND managed = TRUE
            LIMIT 1
            """, (current.account_id, current.net_position_id, int(current.uic), current.asset_type),
        ).fetchone()
    if row is None:
        return False
    return str(_record_dict(row).get("direction") or "").strip().lower() == current.direction.strip().lower()


def run_strategy_live_close_cycle_v2() -> StrategyCloseCycleV2:
    if not using_postgres():
        return StrategyCloseCycleV2(False, 0, 0, 0, 0, 0)
    ensure_autotrader_schema_v2()

    pending = _pending_close_requests()
    config = load_live_close_config_v1()
    config_armed = bool(config.armed)
    code_gate = bool(code_gate_enabled_v1())
    armed = bool(config_armed and code_gate)
    _log_pending_close_health(pending, config_armed=config_armed, code_gate=code_gate)
    if not armed:
        return StrategyCloseCycleV2(False, len(pending), 0, 0, 0, 0)

    client = _require_live_client()
    if _position_netting_mode(client).lower() != "intraday":
        LOGGER.error("strategy LIVE close blocked: Saxo PositionNettingMode must be Intraday pending=%d", len(pending))
        return StrategyCloseCycleV2(True, len(pending), 0, 0, 1, 0)

    _reconcile_accepted_attempts(client)
    reconciled = _sync_close_attempt_statuses()
    pending = _pending_close_requests()
    if not pending:
        return StrategyCloseCycleV2(True, 0, 0, reconciled, 0, 0)

    observations = _position_observations_v2(client)
    submitted = blocked = failed = 0
    for request in pending:
        request_id = str(request["request_id"])
        try:
            enrollment = load_strategy_enrollment_v2(str(request["pilot_key"]))
            if enrollment is None or not enrollment.enabled or enrollment.execution_mode != EXECUTION_MODE_LIVE or enrollment.strategy_key != str(request["strategy_key"]) or enrollment.account_id != str(request["account_id"]) or int(enrollment.uic) != int(request["uic"]) or enrollment.asset_type != str(request["asset_type"]):
                _update_request(request_id, status=REQUEST_BLOCKED, block_reason="LIVE_ENROLLMENT_MISMATCH")
                LOGGER.warning("strategy CLOSE blocked request=%s reason=LIVE_ENROLLMENT_MISMATCH", request_id)
                blocked += 1
                continue

            current = _matching_current_position(request, observations)
            if current is None:
                _update_request(request_id, status=REQUEST_RECONCILED, block_reason="ALREADY_FLAT_NO_ORDER")
                LOGGER.info("strategy CLOSE reconciled request=%s reason=ALREADY_FLAT_NO_ORDER", request_id)
                reconciled += 1
                continue

            exact_managed = is_position_managed_v1(current)
            binary_managed_identity = _binary_macd_managed_identity_is_authorized(request, current)
            if not exact_managed and not binary_managed_identity:
                _update_request(request_id, status=REQUEST_BLOCKED, block_reason="POSITION_NOT_EXACTLY_MANAGED")
                LOGGER.warning("strategy CLOSE blocked request=%s reason=POSITION_NOT_EXACTLY_MANAGED", request_id)
                blocked += 1
                continue

            if not _basis_is_unchanged(request, current):
                if binary_managed_identity:
                    LOGGER.info("binary MACD close rebased request=%s side=%s old_amount=%s current_amount=%s", request_id, _direction_v2(current), request.get("observed_amount"), current.amount)
                else:
                    _update_request(request_id, status=REQUEST_BLOCKED, block_reason="STALE_POSITION_BASIS")
                    LOGGER.warning("strategy CLOSE blocked request=%s reason=STALE_POSITION_BASIS", request_id)
                    blocked += 1
                    continue
            if not current.can_be_closed or not current.is_market_open or current.non_tradable_reason not in {"", "None", "NONE", None}:
                LOGGER.warning("strategy CLOSE waiting request=%s can_be_closed=%s market_open=%s non_tradable_reason=%s", request_id, current.can_be_closed, current.is_market_open, current.non_tradable_reason)
                continue

            account_key = _account_key_for_account_id(client, current.account_id)
            external_reference = f"pg-strategy-close-{request_id.replace('-', '')[:30]}"
            payload = _close_payload(account_key=account_key, observation=current, external_reference=external_reference)
            precheck = _post_once(client, "trade/v2/orders/precheck", payload)
            if not _precheck_is_clear(precheck):
                diagnostic = precheck_failure_diagnostics_v1(precheck)
                _update_request(request_id, status=REQUEST_BLOCKED, block_reason=diagnostic.block_reason)
                LOGGER.warning(
                    "strategy CLOSE precheck blocked request=%s result=%s error_code=%s error_message=%s disclaimers=%s response_keys=%s side=%s amount=%s uic=%s asset_type=%s position_id=%s",
                    request_id,
                    diagnostic.result,
                    diagnostic.error_code or "none",
                    diagnostic.error_message or "none",
                    diagnostic.has_disclaimers,
                    ",".join(diagnostic.response_keys),
                    payload.get("BuySell"),
                    payload.get("Amount"),
                    payload.get("Uic"),
                    payload.get("AssetType"),
                    payload.get("PositionId") or "none",
                )
                blocked += 1
                continue

            if not _record_attempt_before_submit(event_id=request_id, observation=current, close_side=str(payload["BuySell"]), external_reference=external_reference, precheck_result=str(precheck.get("PreCheckResult") or "")):
                LOGGER.info("strategy CLOSE existing attempt request=%s; reconciling instead of duplicate submit", request_id)
                _sync_close_attempt_statuses()
                continue

            _update_request(request_id, status=REQUEST_SUBMITTING)
            LOGGER.warning("strategy CLOSE submitting request=%s observed=%s desired=%s amount=%s", request_id, _direction_v2(current), request.get("desired_direction"), current.amount)
            try:
                response = _post_once(client, "trade/v2/orders", payload)
            except SaxoError as exc:
                uncertain = str(getattr(exc, "status", "")).upper() in {"TIMEOUT", "CONNECTION_FAILED", "REQUEST_FAILED", "INVALID_RESPONSE"}
                attempt_status = STATUS_UNCERTAIN if uncertain else STATUS_REJECTED
                request_status = REQUEST_UNCERTAIN if uncertain else REQUEST_REJECTED
                _update_attempt(request_id, status=attempt_status, error=str(exc))
                _update_request(request_id, status=request_status, block_reason=str(exc))
                LOGGER.error("strategy CLOSE %s request=%s error=%s", "uncertain" if uncertain else "rejected", request_id, exc)
                failed += 1
                continue

            order_value = response.get("OrderId") or response.get("OrderIds")
            order_id = str(order_value[0]) if isinstance(order_value, list) and order_value else (None if order_value is None else str(order_value))
            _update_attempt(request_id, status=STATUS_ORDER_ACCEPTED, order_id=order_id)
            _update_request(request_id, status=REQUEST_ORDER_ACCEPTED, order_id=order_id)
            LOGGER.warning("strategy CLOSE accepted request=%s order_id=%s", request_id, order_id)
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
            adoption = run_manual_entry_adoption_cycle_v2()
            if adoption.adopted or adoption.failed:
                LOGGER.info("Manage-only adoption candidates=%d adopted=%d unchanged=%d failed=%d", adoption.candidates, adoption.adopted, adoption.unchanged, adoption.failed)
        except Exception as exc:
            LOGGER.warning("Manage-only adoption cycle failed: %s", exc, exc_info=True)
        try:
            run_strategy_live_close_cycle_v2()
        except Exception as exc:
            LOGGER.warning("strategy LIVE close cycle failed: %s", exc, exc_info=True)
        sleep_to_fixed_start_cadence_v2(started, interval)


__all__ = ["StrategyCloseCycleV2", "run_strategy_live_close_cycle_v2", "run_strategy_live_close_forever_v2"]
