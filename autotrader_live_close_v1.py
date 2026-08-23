from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import time
from typing import Any

import requests

from autotrader_managed_positions_v1 import (
    ensure_managed_positions_schema_v1,
    is_position_managed_v1,
)
from autotrader_risk_dry_run_v2 import (
    ACTION_WOULD_CLOSE,
    PositionObservationV2,
    evaluate_risk_v2,
    load_risk_config_v2,
    _position_observations_v2,
)
from database import connect, using_postgres
from saxo_provider import LIVE_BASE_URL, SaxoClient, SaxoError, configured_client


LOGGER = logging.getLogger("pricegauger.autotrader.live_close_v1")
CODE_GATE_ENV = "PRICEGAUGER_AUTOTRADER_LIVE_CLOSE_CODE_ENABLED"
STATUS_SUBMITTING = "SUBMITTING"
STATUS_ORDER_ACCEPTED = "ORDER_ACCEPTED"
STATUS_RECONCILED = "RECONCILED"
STATUS_REJECTED = "REJECTED"
STATUS_UNCERTAIN = "UNCERTAIN"
STATUS_STALE_TRIGGER = "STALE_TRIGGER"


@dataclass(frozen=True, slots=True)
class LiveCloseConfigV1:
    armed: bool = False


@dataclass(frozen=True, slots=True)
class LiveCloseCycleSummaryV1:
    armed: bool
    candidates: int
    submitted: int
    reconciled: int
    blocked: int
    failed: int


def code_gate_enabled_v1() -> bool:
    value = os.getenv(CODE_GATE_ENV, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def ensure_live_close_schema_v1() -> None:
    if not using_postgres():
        raise RuntimeError("LIVE close-only execution requires PostgreSQL")
    with connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pg_v2_autotrader_live_close_config (
                config_id SMALLINT PRIMARY KEY CHECK (config_id = 1),
                armed BOOLEAN NOT NULL DEFAULT FALSE,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_live_close_config (config_id, armed)
            VALUES (1, FALSE)
            ON CONFLICT (config_id) DO NOTHING
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pg_v2_autotrader_live_close_attempts (
                event_id UUID PRIMARY KEY,
                account_id TEXT NOT NULL,
                net_position_id TEXT NOT NULL,
                uic BIGINT NOT NULL,
                asset_type TEXT NOT NULL,
                close_side TEXT NOT NULL,
                amount DOUBLE PRECISION NOT NULL,
                external_reference TEXT NOT NULL,
                status TEXT NOT NULL,
                order_id TEXT,
                precheck_result TEXT,
                error_message TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    ensure_managed_positions_schema_v1()


def load_live_close_config_v1() -> LiveCloseConfigV1:
    ensure_live_close_schema_v1()
    with connect() as db:
        row = db.execute(
            "SELECT armed FROM pg_v2_autotrader_live_close_config WHERE config_id = 1"
        ).fetchone()
    if row is None:
        return LiveCloseConfigV1()
    if isinstance(row, dict):
        return LiveCloseConfigV1(armed=bool(row.get("armed")))
    return LiveCloseConfigV1(armed=bool(row[0]))


def save_live_close_config_v1(config: LiveCloseConfigV1) -> LiveCloseConfigV1:
    ensure_live_close_schema_v1()
    with connect() as db:
        db.execute(
            """
            UPDATE pg_v2_autotrader_live_close_config
            SET armed = ?, updated_at = now()
            WHERE config_id = 1
            """,
            (bool(config.armed),),
        )
    return config


def _latest_triggered_states() -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute(
            """
            SELECT account_id, net_position_id, uic, asset_type, direction, amount,
                   average_open_price, current_price, pnl_pct, high_water_pct,
                   price_delay_minutes, can_be_closed, calculation_reliability,
                   is_market_open, non_tradable_reason, triggered_reason, triggered_at
            FROM pg_v2_autotrader_risk_state
            WHERE active = TRUE AND triggered_reason IS NOT NULL
            ORDER BY triggered_at ASC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def _latest_event_id(account_id: str, net_position_id: str) -> str | None:
    with connect() as db:
        row = db.execute(
            """
            SELECT event_id
            FROM pg_v2_autotrader_risk_events
            WHERE account_id = ? AND net_position_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (account_id, net_position_id),
        ).fetchone()
    if row is None:
        return None
    if isinstance(row, dict):
        value = row.get("event_id")
    else:
        value = row[0]
    return str(value) if value else None


def _attempt_status(event_id: str) -> str | None:
    with connect() as db:
        row = db.execute(
            "SELECT status FROM pg_v2_autotrader_live_close_attempts WHERE event_id = ?",
            (event_id,),
        ).fetchone()
    if row is None:
        return None
    return str(row.get("status") if isinstance(row, dict) else row[0])


def _record_attempt_before_submit(
    *,
    event_id: str,
    observation: PositionObservationV2,
    close_side: str,
    external_reference: str,
    precheck_result: str,
) -> bool:
    with connect() as db:
        existing = db.execute(
            "SELECT status FROM pg_v2_autotrader_live_close_attempts WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        if existing is not None:
            return False
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_live_close_attempts
                (event_id, account_id, net_position_id, uic, asset_type, close_side,
                 amount, external_reference, status, precheck_result)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                observation.account_id,
                observation.net_position_id,
                observation.uic,
                observation.asset_type,
                close_side,
                observation.amount,
                external_reference,
                STATUS_SUBMITTING,
                precheck_result,
            ),
        )
    return True


def _update_attempt(event_id: str, *, status: str, order_id: str | None = None, error: str | None = None) -> None:
    with connect() as db:
        db.execute(
            """
            UPDATE pg_v2_autotrader_live_close_attempts
            SET status = ?, order_id = COALESCE(?, order_id),
                error_message = ?, updated_at = now()
            WHERE event_id = ?
            """,
            (status, order_id, error, event_id),
        )


def _require_live_client() -> SaxoClient:
    client = configured_client()
    if client is None:
        raise RuntimeError("Saxo client is not configured")
    if client.base_url.rstrip("/").lower() != LIVE_BASE_URL.lower():
        raise RuntimeError("LIVE close-only adapter refuses non-LIVE Saxo environment")
    return client


def _account_key_for_account_id(client: SaxoClient, account_id: str) -> str:
    payload = client._get("port/v1/accounts/me")
    rows = payload.get("Data") or []
    if not isinstance(rows, list):
        raise SaxoError("account list had invalid format", status="INVALID_RESPONSE")
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("AccountId") or "") == str(account_id) and row.get("AccountKey"):
            if not bool(row.get("Active", True)):
                raise RuntimeError("position account is not active")
            return str(row["AccountKey"])
    raise RuntimeError("could not resolve AccountKey for triggered position")


def _position_netting_mode(client: SaxoClient) -> str:
    payload = client._get("port/v1/clients/me")
    return str(payload.get("PositionNettingMode") or "")


def _close_payload(
    *,
    account_key: str,
    observation: PositionObservationV2,
    external_reference: str,
) -> dict[str, Any]:
    opening = observation.direction.strip().title()
    if opening == "Buy":
        side = "Sell"
    elif opening == "Sell":
        side = "Buy"
    else:
        raise RuntimeError(f"unsupported position direction: {observation.direction}")
    if observation.amount <= 0:
        raise RuntimeError("position amount must be positive")
    return {
        "AccountKey": account_key,
        "Amount": float(observation.amount),
        "AssetType": observation.asset_type,
        "BuySell": side,
        "ExternalReference": external_reference[:50],
        "IsForceOpen": False,
        "ManualOrder": False,
        "OrderDuration": {"DurationType": "DayOrder"},
        "OrderType": "Market",
        "Uic": int(observation.uic),
    }


def _post_once(client: SaxoClient, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    client._set_authorization(force_refresh=False)
    url = f"{client.base_url}/{path.lstrip('/')}"
    try:
        response = client.session.post(url, json=payload, timeout=client.timeout)
    except requests.Timeout as exc:
        raise SaxoError(f"timeout after {client.timeout:g} seconds", status="TIMEOUT") from exc
    except requests.ConnectionError as exc:
        raise SaxoError("connection failed", status="CONNECTION_FAILED") from exc
    except requests.RequestException as exc:
        raise SaxoError(type(exc).__name__, status="REQUEST_FAILED") from exc
    try:
        body = response.json()
    except ValueError as exc:
        raise SaxoError("response was not valid JSON", status="INVALID_RESPONSE", status_code=response.status_code) from exc
    if not response.ok:
        message = "request rejected"
        if isinstance(body, dict):
            error_info = body.get("ErrorInfo") if isinstance(body.get("ErrorInfo"), dict) else {}
            message = str(
                error_info.get("Message")
                or error_info.get("ErrorCode")
                or body.get("Message")
                or body.get("message")
                or message
            )
        status = "AUTH_FAILED" if response.status_code in {401, 403} else "REQUEST_FAILED"
        raise SaxoError(message, status=status, status_code=response.status_code)
    if not isinstance(body, dict):
        raise SaxoError("expected JSON object", status="INVALID_RESPONSE", status_code=response.status_code)
    return body


def _precheck_is_clear(payload: dict[str, Any]) -> bool:
    return str(payload.get("PreCheckResult") or "").lower() == "ok" and not bool(payload.get("PreTradeDisclaimers"))


def _current_observation(client: SaxoClient, account_id: str, net_position_id: str) -> PositionObservationV2 | None:
    for observation in _position_observations_v2(client):
        if observation.account_id == account_id and observation.net_position_id == net_position_id:
            return observation
    return None


def _same_trigger_basis(state: dict[str, Any], current: PositionObservationV2) -> bool:
    if int(state["uic"]) != int(current.uic):
        return False
    if str(state["asset_type"]) != str(current.asset_type):
        return False
    if str(state["direction"]).lower() != current.direction.lower():
        return False
    if abs(float(state["amount"]) - float(current.amount)) > 1e-12:
        return False
    if abs(float(state["average_open_price"]) - float(current.average_open_price)) > 1e-12:
        return False
    return True


def _reconcile_accepted_attempts(client: SaxoClient) -> int:
    with connect() as db:
        rows = db.execute(
            """
            SELECT event_id, account_id, net_position_id, amount
            FROM pg_v2_autotrader_live_close_attempts
            WHERE status = ?
            ORDER BY updated_at ASC
            """,
            (STATUS_ORDER_ACCEPTED,),
        ).fetchall()
    if not rows:
        return 0
    observations = {(o.account_id, o.net_position_id): o for o in _position_observations_v2(client)}
    reconciled = 0
    for row in rows:
        item = dict(row)
        current = observations.get((str(item["account_id"]), str(item["net_position_id"])))
        if current is None or current.amount < float(item["amount"]) - 1e-12:
            _update_attempt(str(item["event_id"]), status=STATUS_RECONCILED)
            reconciled += 1
    return reconciled


def run_live_close_cycle_v1() -> LiveCloseCycleSummaryV1:
    ensure_live_close_schema_v1()
    config = load_live_close_config_v1()
    if not config.armed or not code_gate_enabled_v1():
        return LiveCloseCycleSummaryV1(
            armed=False,
            candidates=0,
            submitted=0,
            reconciled=0,
            blocked=0,
            failed=0,
        )

    client = _require_live_client()
    netting_mode = _position_netting_mode(client)
    if netting_mode.lower() != "intraday":
        LOGGER.error("LIVE close-only blocked: PositionNettingMode=%s; Intraday required", netting_mode)
        return LiveCloseCycleSummaryV1(True, 0, 0, 0, 1, 0)

    reconciled = _reconcile_accepted_attempts(client)
    states = _latest_triggered_states()
    submitted = 0
    blocked = 0
    failed = 0
    risk_config = load_risk_config_v2()

    for state in states:
        account_id = str(state["account_id"])
        net_position_id = str(state["net_position_id"])
        event_id = _latest_event_id(account_id, net_position_id)
        if not event_id:
            blocked += 1
            continue
        if _attempt_status(event_id) is not None:
            continue
        try:
            current = _current_observation(client, account_id, net_position_id)
            if current is None:
                blocked += 1
                continue
            if not is_position_managed_v1(current):
                LOGGER.info("LIVE close ignored unmanaged position=%s", net_position_id)
                blocked += 1
                continue
            if not _same_trigger_basis(state, current):
                LOGGER.warning("LIVE close trigger went stale before execution position=%s", net_position_id)
                blocked += 1
                continue

            fresh_decision = evaluate_risk_v2(
                current,
                config=risk_config,
                previous_high_water_pct=float(state["high_water_pct"]),
                already_triggered_reason=None,
            )
            if fresh_decision.action != ACTION_WOULD_CLOSE or not fresh_decision.eligible_for_execution:
                blocked += 1
                continue

            account_key = _account_key_for_account_id(client, account_id)
            external_reference = f"pg-close-{event_id.replace('-', '')[:32]}"
            payload = _close_payload(
                account_key=account_key,
                observation=current,
                external_reference=external_reference,
            )
            precheck = _post_once(client, "trade/v2/orders/precheck", payload)
            precheck_result = str(precheck.get("PreCheckResult") or "")
            if not _precheck_is_clear(precheck):
                LOGGER.warning(
                    "LIVE close precheck blocked position=%s result=%s disclaimers=%s",
                    net_position_id,
                    precheck_result,
                    bool(precheck.get("PreTradeDisclaimers")),
                )
                blocked += 1
                continue

            close_side = str(payload["BuySell"])
            if not _record_attempt_before_submit(
                event_id=event_id,
                observation=current,
                close_side=close_side,
                external_reference=external_reference,
                precheck_result=precheck_result,
            ):
                continue

            try:
                response = _post_once(client, "trade/v2/orders", payload)
            except SaxoError as exc:
                if exc.status in {"TIMEOUT", "CONNECTION_FAILED", "INVALID_RESPONSE"}:
                    _update_attempt(event_id, status=STATUS_UNCERTAIN, error=str(exc))
                else:
                    _update_attempt(event_id, status=STATUS_REJECTED, error=str(exc))
                raise

            order_value = response.get("OrderId") or response.get("OrderIds")
            if isinstance(order_value, list):
                order_id = str(order_value[0]) if order_value else None
            else:
                order_id = str(order_value) if order_value else None
            _update_attempt(event_id, status=STATUS_ORDER_ACCEPTED, order_id=order_id)
            submitted += 1
            LOGGER.warning(
                "LIVE close order accepted position=%s event=%s order_id=%s side=%s amount=%s reason=%s pnl=%.3f%%",
                net_position_id,
                event_id,
                order_id,
                close_side,
                current.amount,
                fresh_decision.reason,
                current.pnl_pct,
            )
        except Exception as exc:
            failed += 1
            LOGGER.exception("LIVE close candidate failed position=%s: %s", net_position_id, exc)

    return LiveCloseCycleSummaryV1(
        armed=True,
        candidates=len(states),
        submitted=submitted,
        reconciled=reconciled,
        blocked=blocked,
        failed=failed,
    )


def run_live_close_forever_v1(*, interval_seconds: int = 2) -> None:
    interval = max(1, int(interval_seconds))
    ensure_live_close_schema_v1()
    while True:
        try:
            summary = run_live_close_cycle_v1()
            if summary.armed or summary.submitted or summary.failed:
                LOGGER.info(
                    "LIVE close cycle armed=%s candidates=%d submitted=%d reconciled=%d blocked=%d failed=%d",
                    summary.armed,
                    summary.candidates,
                    summary.submitted,
                    summary.reconciled,
                    summary.blocked,
                    summary.failed,
                )
        except Exception as exc:
            LOGGER.exception("LIVE close cycle failed before candidate execution: %s", exc)
        time.sleep(interval)
