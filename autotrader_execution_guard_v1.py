from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import os
import time
from typing import Any, Mapping

import requests

from autotrader_manage_control_v1 import auto_manage_enabled_v1, set_auto_manage_enabled_v1
from autotrader_risk_control_v2 import PositionObservationV2
from autotrader_strategy_enrollment_v2 import (
    ENTRY_MODE_MANUAL_ONLY,
    EXECUTION_MODE_LIVE,
    StrategyEnrollmentV2,
    load_active_strategy_enrollments_v2,
    load_strategy_enrollment_v2,
)
from database import connect
from saxo_provider import SaxoClient, SaxoError

LOGGER = logging.getLogger("pricegauger.autotrader.execution_guard_v1")
PG_OPEN_PREFIX = "pg-open-"
PG_CLOSE_PREFIX = "pg-close-"
MAX_AGE = timedelta(minutes=90)
CODE_GATE_ENV = "PRICEGAUGER_AUTOTRADER_LIVE_OPEN_CODE_ENABLED"
SWEEP_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class WorkingOrderGuardCycleV1:
    observed: int
    pg_owned: int
    cancelled: int
    unknown: int
    unresolved: int


def _dict(row: Any) -> dict[str, Any]:
    return row if isinstance(row, dict) else dict(row)


def _scalar(row: Any, key: str, index: int = 0) -> Any:
    return row.get(key) if isinstance(row, Mapping) else row[index]


def _utc(value: Any) -> datetime:
    item = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if item.tzinfo is None:
        item = item.replace(tzinfo=timezone.utc)
    return item.astimezone(timezone.utc)


def ensure_execution_guard_schema_v1() -> None:
    with connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pg_v2_autotrader_execution_anomalies (
                anomaly_key TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                severity TEXT NOT NULL,
                account_id TEXT,
                uic BIGINT,
                asset_type TEXT,
                order_id TEXT,
                external_reference TEXT,
                request_id UUID,
                net_position_id TEXT,
                details TEXT NOT NULL DEFAULT '',
                active BOOLEAN NOT NULL DEFAULT TRUE,
                first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                resolved_at TIMESTAMPTZ
            )
            """
        )


def _anomaly(
    kind: str,
    *,
    account_id: str | None,
    uic: int | None,
    asset_type: str | None,
    order_id: str | None = None,
    external_reference: str | None = None,
    request_id: str | None = None,
    net_position_id: str | None = None,
    details: str = "",
    severity: str = "HIGH",
) -> None:
    ensure_execution_guard_schema_v1()
    key = "|".join(str(v or "") for v in (kind, account_id, uic, asset_type, order_id, request_id, net_position_id))
    with connect() as db:
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_execution_anomalies(
                anomaly_key, kind, severity, account_id, uic, asset_type,
                order_id, external_reference, request_id, net_position_id,
                details, active, first_seen_at, last_seen_at, resolved_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, TRUE, now(), now(), NULL)
            ON CONFLICT (anomaly_key) DO UPDATE SET
                severity=EXCLUDED.severity, details=EXCLUDED.details,
                active=TRUE, last_seen_at=now(), resolved_at=NULL
            """,
            (key, kind, severity, account_id, uic, asset_type, order_id,
             external_reference, request_id, net_position_id, details),
        )


def _accounts(client: SaxoClient) -> tuple[dict[str, str], dict[str, str]]:
    payload = client._get("port/v1/accounts/me", params={"$top": 1000})
    rows = payload.get("Data") or []
    if not isinstance(rows, list):
        raise RuntimeError("Saxo account list had invalid format")
    key_to_id: dict[str, str] = {}
    id_to_key: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        key = str(row.get("AccountKey") or "").strip()
        account_id = str(row.get("AccountId") or "").strip()
        if key and account_id:
            key_to_id[key] = account_id
            id_to_key[account_id] = key
    return key_to_id, id_to_key


def _orders(client: SaxoClient) -> tuple[dict[str, Any], ...]:
    payload = client._get("port/v1/orders/me", params={"$top": 1000})
    rows = payload.get("Data") or []
    if not isinstance(rows, list):
        raise RuntimeError("Saxo open-order list had invalid format")
    return tuple(dict(row) for row in rows if isinstance(row, Mapping))


def _request_by_ref(reference: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute(
            """
            SELECT req.request_id, req.pilot_key, req.strategy_key, req.action,
                   req.desired_direction, req.signal_at, req.signal, req.account_id,
                   req.uic, req.asset_type, req.status, req.created_at,
                   att.status AS attempt_status, att.order_id, att.amount,
                   att.external_reference
            FROM pg_v2_autotrader_live_open_attempts att
            JOIN pg_v2_autotrader_execution_requests req ON req.request_id=att.request_id
            WHERE att.external_reference=? LIMIT 1
            """,
            (reference,),
        ).fetchone()
    return None if row is None else _dict(row)


def _newer_intent(request: Mapping[str, Any]) -> bool:
    with connect() as db:
        row = db.execute(
            """SELECT 1 FROM pg_v2_autotrader_strategy_evaluations
               WHERE pilot_key=? AND intent_id IS NOT NULL AND signal_at>? LIMIT 1""",
            (str(request["pilot_key"]), request["signal_at"]),
        ).fetchone()
    return row is not None


def _request_current(request: Mapping[str, Any]) -> bool:
    if str(request.get("action")) != "OPEN" or str(request.get("status")) not in {"SUBMITTING", "ORDER_ACCEPTED"}:
        return False
    age = datetime.now(timezone.utc) - _utc(request["signal_at"])
    if age < timedelta(0) or age > MAX_AGE:
        return False
    enrollment = load_strategy_enrollment_v2(str(request["pilot_key"]))
    if (
        enrollment is None or not enrollment.enabled or enrollment.execution_mode != EXECUTION_MODE_LIVE
        or enrollment.strategy_key != str(request["strategy_key"])
        or enrollment.account_id != str(request["account_id"])
        or int(enrollment.uic) != int(request["uic"])
        or enrollment.asset_type != str(request["asset_type"])
        or not enrollment.live_open_armed or enrollment.entry_mode == ENTRY_MODE_MANUAL_ONLY
    ):
        return False
    with connect() as db:
        armed = db.execute("SELECT armed FROM pg_v2_autotrader_live_open_config WHERE config_id=1").fetchone()
        updated = db.execute("SELECT updated_at FROM pg_v2_autotrader_strategy_enrollments WHERE pilot_key=?", (enrollment.pilot_key,)).fetchone()
    if armed is None or not bool(_scalar(armed, "armed")):
        return False
    if os.getenv(CODE_GATE_ENV, "").strip().lower() not in {"1", "true", "yes", "on"}:
        return False
    if updated is None or _utc(_scalar(updated, "updated_at")) > _utc(request["created_at"]):
        return False
    if not str(request.get("signal") or "").startswith("USER_TARGET_") and not auto_manage_enabled_v1(enrollment):
        return False
    return not _newer_intent(request)


def _pause(enrollment: StrategyEnrollmentV2, reason: str) -> None:
    if auto_manage_enabled_v1(enrollment):
        set_auto_manage_enabled_v1(enrollment, False)
        LOGGER.error("AutoManager paused by execution guard pilot=%s reason=%s", enrollment.pilot_key, reason)


def _enrollment(account_id: str | None, uic: int | None, asset_type: str | None) -> StrategyEnrollmentV2 | None:
    if not account_id or uic is None:
        return None
    matches = tuple(
        e for e in load_active_strategy_enrollments_v2()
        if e.enabled and e.execution_mode == EXECUTION_MODE_LIVE
        and e.account_id == account_id and int(e.uic) == int(uic)
        and (not asset_type or e.asset_type == asset_type)
    )
    if len(matches) > 1:
        raise RuntimeError("multiple LIVE enrollments matched one Saxo working order")
    return matches[0] if matches else None


def _delete_order_once_v1(client: SaxoClient, *, account_key: str, order_id: str) -> None:
    client._set_authorization(force_refresh=False)
    url = f"{client.base_url}/trade/v2/orders/{order_id}"
    try:
        response = client.session.delete(url, params={"AccountKey": account_key}, timeout=client.timeout)
    except requests.Timeout as exc:
        raise SaxoError("order cancel timeout", status="TIMEOUT") from exc
    except requests.RequestException as exc:
        raise SaxoError(type(exc).__name__, status="REQUEST_FAILED") from exc
    if response.status_code not in {200, 204}:
        raise SaxoError("order cancel rejected", status="REQUEST_FAILED", status_code=response.status_code)
    if not response.content:
        return
    try:
        body = response.json()
    except ValueError:
        return
    errors = []
    if isinstance(body, Mapping) and isinstance(body.get("ErrorInfo"), Mapping):
        errors.append(body["ErrorInfo"])
    if isinstance(body, Mapping) and isinstance(body.get("Orders"), list):
        errors.extend(item.get("ErrorInfo") for item in body["Orders"] if isinstance(item, Mapping) and isinstance(item.get("ErrorInfo"), Mapping))
    if errors:
        error = errors[0]
        raise SaxoError(str(error.get("Message") or error.get("ErrorCode") or "order cancel rejected"), status="REQUEST_FAILED")


def _mark(request: Mapping[str, Any], status: str, reason: str) -> None:
    request_id = str(request["request_id"])
    with connect() as db:
        db.execute("UPDATE pg_v2_autotrader_live_open_attempts SET status=?, error_message=?, updated_at=now() WHERE request_id=?", (status, reason, request_id))
        db.execute("UPDATE pg_v2_autotrader_execution_requests SET status=?, block_reason=?, updated_at=now() WHERE request_id=?", ("BLOCKED" if status != "UNCERTAIN" else "UNCERTAIN", reason, request_id))


def require_market_open_for_open_v1(client: SaxoClient, *, account_id: str, uic: int, asset_type: str) -> None:
    _, id_to_key = _accounts(client)
    account_key = id_to_key.get(account_id)
    if not account_key:
        raise ValueError("MARKET_OPEN_PRECHECK_ACCOUNT_UNRESOLVED")
    payload = client._get("trade/v1/infoprices", params={
        "AccountKey": account_key, "Uic": int(uic), "AssetType": asset_type,
        "FieldGroups": "InstrumentPriceDetails,Quote",
    })
    details = payload.get("InstrumentPriceDetails") if isinstance(payload.get("InstrumentPriceDetails"), Mapping) else {}
    quote = payload.get("Quote") if isinstance(payload.get("Quote"), Mapping) else {}
    if details.get("IsMarketOpen") is not True:
        raise ValueError("SAXO_MARKET_NOT_EXPLICITLY_OPEN")
    if quote.get("ErrorCode"):
        raise ValueError(f"SAXO_MARKET_QUOTE_ERROR:{quote.get('ErrorCode')}")


def sweep_working_orders_v1(client: SaxoClient) -> WorkingOrderGuardCycleV1:
    """Cancel only stale PG OPEN orders; foreign orders are never auto-cancelled."""
    ensure_execution_guard_schema_v1()
    key_to_id, _ = _accounts(client)
    orders = _orders(client)
    pg_owned = cancelled = unknown = unresolved = 0
    for order in orders:
        account_key = str(order.get("AccountKey") or "")
        account_id = key_to_id.get(account_key)
        uic = None if order.get("Uic") is None else int(order["Uic"])
        asset_type = None if order.get("AssetType") is None else str(order["AssetType"])
        order_id = str(order.get("OrderId") or "")
        ref = str(order.get("ExternalReference") or "")
        enrollment = _enrollment(account_id, uic, asset_type)
        if ref.startswith(PG_CLOSE_PREFIX):
            continue
        if not ref.startswith(PG_OPEN_PREFIX):
            if enrollment is not None:
                unknown += 1
                _anomaly("UNKNOWN_WORKING_ORDER", account_id=account_id, uic=uic, asset_type=asset_type or enrollment.asset_type, order_id=order_id or None, external_reference=ref or None, details="Foreign/manual working order left untouched; AutoManager paused")
                _pause(enrollment, "UNKNOWN_WORKING_ORDER")
            continue
        pg_owned += 1
        request = _request_by_ref(ref)
        current = request is not None and _request_current(request)
        if current and request is not None:
            try:
                require_market_open_for_open_v1(client, account_id=str(request["account_id"]), uic=int(request["uic"]), asset_type=str(request["asset_type"]))
            except Exception:
                current = False
        if current:
            continue
        request_id = None if request is None else str(request["request_id"])
        _anomaly("STALE_PG_WORKING_ORDER", account_id=account_id, uic=uic, asset_type=asset_type or (None if enrollment is None else enrollment.asset_type), order_id=order_id or None, external_reference=ref, request_id=request_id, details="PG broker order outlived current OPEN authority", severity="CRITICAL")
        try:
            if not account_key or not order_id:
                raise RuntimeError("working order lacks Saxo identity")
            _delete_order_once_v1(client, account_key=account_key, order_id=order_id)
        except Exception as exc:
            unresolved += 1
            if request is not None:
                _mark(request, "UNCERTAIN", f"STALE_WORKING_ORDER_CANCEL_UNCERTAIN:{exc}")
            if enrollment is not None:
                _pause(enrollment, "STALE_WORKING_ORDER_CANCEL_UNCERTAIN")
            LOGGER.exception("Stale PG working-order cancel unresolved order_id=%s", order_id)
            continue
        cancelled += 1
        if request is not None:
            _mark(request, "CANCELLED_STALE", "STALE_WORKING_ORDER_CANCELLED")
        LOGGER.warning("Stale PG working order cancelled order_id=%s ref=%s uic=%s", order_id, ref, uic)
    return WorkingOrderGuardCycleV1(len(orders), pg_owned, cancelled, unknown, unresolved)


def _request_for_position(enrollment: StrategyEnrollmentV2, observation: PositionObservationV2) -> dict[str, Any] | None:
    desired = "LONG" if observation.direction.strip().lower() == "buy" else "SHORT"
    with connect() as db:
        rows = db.execute(
            """
            SELECT req.request_id, req.pilot_key, req.strategy_key, req.action,
                   req.desired_direction, req.signal_at, req.signal, req.account_id,
                   req.uic, req.asset_type, req.status, req.created_at,
                   att.status AS attempt_status, att.order_id, att.amount, att.external_reference
            FROM pg_v2_autotrader_live_open_attempts att
            JOIN pg_v2_autotrader_execution_requests req ON req.request_id=att.request_id
            WHERE req.pilot_key=? AND req.account_id=? AND req.uic=? AND req.asset_type=?
              AND req.action='OPEN' AND req.desired_direction=?
            ORDER BY att.updated_at DESC LIMIT 5
            """,
            (enrollment.pilot_key, enrollment.account_id, int(enrollment.uic), enrollment.asset_type, desired),
        ).fetchall()
    for row in rows:
        request = _dict(row)
        if abs(float(request.get("amount") or 0) - float(observation.amount)) <= 1e-9 and (
            str(request.get("attempt_status")) == "RECONCILED" or _request_current(request)
        ):
            return request
    return None


def auto_adoption_has_provenance_v1(enrollment: StrategyEnrollmentV2, observation: PositionObservationV2) -> bool:
    if _request_for_position(enrollment, observation) is not None:
        return True
    _anomaly("UNEXPECTED_POSITION_ORIGIN", account_id=enrollment.account_id, uic=enrollment.uic, asset_type=enrollment.asset_type, net_position_id=observation.net_position_id, details="Unmanaged Saxo position has no current PG OPEN provenance", severity="CRITICAL")
    _pause(enrollment, "UNEXPECTED_POSITION_ORIGIN")
    return False


def filter_reconcilable_open_attempts_v1(attempts: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
    result = []
    for attempt in attempts:
        request_id = str(attempt.get("request_id") or "")
        with connect() as db:
            row = db.execute(
                """SELECT req.request_id, req.pilot_key, req.strategy_key, req.action,
                          req.desired_direction, req.signal_at, req.signal, req.account_id,
                          req.uic, req.asset_type, req.status, req.created_at,
                          att.status AS attempt_status, att.order_id, att.amount, att.external_reference
                   FROM pg_v2_autotrader_execution_requests req
                   JOIN pg_v2_autotrader_live_open_attempts att ON att.request_id=req.request_id
                   WHERE req.request_id=? LIMIT 1""",
                (request_id,),
            ).fetchone()
        if row is not None and _request_current(_dict(row)):
            result.append(attempt)
            continue
        if row is not None:
            request = _dict(row)
            enrollment = load_strategy_enrollment_v2(str(request["pilot_key"]))
            _anomaly("LATE_PG_FILL", account_id=str(request["account_id"]), uic=int(request["uic"]), asset_type=str(request["asset_type"]), order_id=None if request.get("order_id") is None else str(request["order_id"]), external_reference=str(request.get("external_reference") or ""), request_id=request_id, details="Accepted OPEN outlived authority; reconciliation quarantined", severity="CRITICAL")
            _mark(request, "QUARANTINED_STALE", "STALE_ACCEPTED_OPEN_AUTHORITY")
            if enrollment is not None:
                _pause(enrollment, "STALE_ACCEPTED_OPEN_AUTHORITY")
    return tuple(result)


_INSTALLED = False
_LAST_SWEEP = 0.0


def install_execution_safety_guard_v1() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    import autotrader_automanage_dispatch_v2 as dispatch
    import autotrader_live_open_legacy_v2 as live_open

    original_record = live_open._record_attempt_before_submit
    original_accepted = live_open._accepted_attempts
    original_cycle = live_open.run_live_open_cycle_v2
    original_post = live_open._post_once
    original_adopt = dispatch._adopt_observed_basis_if_needed_v1

    def guarded_record(*args, **kwargs):
        request = kwargs.get("request")
        if not isinstance(request, Mapping):
            raise RuntimeError("LIVE OPEN market guard lacks request context")
        require_market_open_for_open_v1(live_open._require_live_client(), account_id=str(request["account_id"]), uic=int(request["uic"]), asset_type=str(request["asset_type"]))
        return original_record(*args, **kwargs)

    def guarded_accepted():
        return filter_reconcilable_open_attempts_v1(original_accepted())

    def guarded_cycle():
        global _LAST_SWEEP
        now = time.monotonic()
        if now - _LAST_SWEEP >= SWEEP_SECONDS:
            summary = sweep_working_orders_v1(live_open._require_live_client())
            _LAST_SWEEP = now
            if summary.cancelled or summary.unknown or summary.unresolved:
                LOGGER.warning("Working-order guard observed=%d cancelled=%d unknown=%d unresolved=%d", summary.observed, summary.cancelled, summary.unknown, summary.unresolved)
        return original_cycle()

    def guarded_post(client, path: str, payload: dict[str, Any]):
        response = original_post(client, path, payload)
        if path.strip("/") == "trade/v2/orders":
            LOGGER.warning("LIVE OPEN broker accepted ref=%s order_id=%s uic=%s side=%s amount=%s", payload.get("ExternalReference"), response.get("OrderId") or response.get("OrderIds"), payload.get("Uic"), payload.get("BuySell"), payload.get("Amount"))
        return response

    def guarded_adopt(enrollment, observations):
        observation = dispatch._exact_product_observation(enrollment, observations)
        if observation is not None and not dispatch.is_position_managed_v1(observation):
            if not auto_adoption_has_provenance_v1(enrollment, observation):
                raise RuntimeError("POSITION_ORIGIN_UNRESOLVED: AutoManager paused; explicit user takeover required")
        return original_adopt(enrollment, observations)

    live_open._record_attempt_before_submit = guarded_record
    live_open._accepted_attempts = guarded_accepted
    live_open.run_live_open_cycle_v2 = guarded_cycle
    live_open._post_once = guarded_post
    dispatch._adopt_observed_basis_if_needed_v1 = guarded_adopt
    _INSTALLED = True


__all__ = [
    "WorkingOrderGuardCycleV1",
    "auto_adoption_has_provenance_v1",
    "ensure_execution_guard_schema_v1",
    "filter_reconcilable_open_attempts_v1",
    "install_execution_safety_guard_v1",
    "require_market_open_for_open_v1",
    "sweep_working_orders_v1",
]
