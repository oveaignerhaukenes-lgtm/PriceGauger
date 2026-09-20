from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import time
from typing import Any, Mapping

from autotrader_strategy_enrollment_v2 import (
    EXECUTION_MODE_LIVE,
    load_active_strategy_enrollments_v2,
)
from database import connect, using_postgres
from saxo_provider import configured_client


LOGGER = logging.getLogger("pricegauger.autotrader.manual_saxo_trade_markers_v1")

DEFAULT_POLL_SECONDS_V1 = 60
INITIAL_LOOKBACK_V1 = timedelta(hours=48)
OVERLAP_V1 = timedelta(minutes=2)


@dataclass(frozen=True, slots=True)
class ManualSaxoTradeMarkerV1:
    log_id: str
    account_id: str
    uic: int
    asset_type: str
    market_name: str
    order_id: str
    position_id: str
    direction: str
    amount: float
    execution_price: float
    executed_at: datetime


def _utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def ensure_manual_saxo_trade_marker_schema_v1() -> None:
    if not using_postgres():
        return
    with connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pg_v2_saxo_manual_trade_markers (
                log_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                uic BIGINT NOT NULL,
                asset_type TEXT NOT NULL,
                market_name TEXT NOT NULL,
                order_id TEXT NOT NULL,
                position_id TEXT NOT NULL DEFAULT '',
                direction TEXT NOT NULL CHECK (direction IN ('LONG','SHORT')),
                amount DOUBLE PRECISION NOT NULL CHECK (amount > 0),
                execution_price DOUBLE PRECISION NOT NULL CHECK (execution_price > 0),
                executed_at TIMESTAMPTZ NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        db.execute(
            """
            CREATE INDEX IF NOT EXISTS pg_v2_saxo_manual_trade_markers_market_time_idx
            ON pg_v2_saxo_manual_trade_markers(market_name, executed_at DESC)
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pg_v2_saxo_manual_trade_marker_sync (
                account_id TEXT PRIMARY KEY,
                last_activity_at TIMESTAMPTZ,
                last_success_at TIMESTAMPTZ,
                last_error TEXT NOT NULL DEFAULT ''
            )
            """
        )


def _active_products_v1() -> dict[str, dict[tuple[int, str], str]]:
    products: dict[str, dict[tuple[int, str], str]] = {}
    for enrollment in load_active_strategy_enrollments_v2():
        if not enrollment.enabled or enrollment.execution_mode != EXECUTION_MODE_LIVE:
            continue
        products.setdefault(enrollment.account_id, {})[
            (int(enrollment.uic), str(enrollment.asset_type))
        ] = str(enrollment.market_name)
    return products


def _account_contexts_v1(client) -> dict[str, tuple[str, str]]:
    payload = client._get("port/v1/accounts/me", params={"$top": 1000})
    rows = payload.get("Data") or []
    if not isinstance(rows, list):
        raise RuntimeError("Saxo accounts response had invalid Data format")
    result: dict[str, tuple[str, str]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        account_id = str(row.get("AccountId") or "").strip()
        account_key = str(row.get("AccountKey") or "").strip()
        client_key = str(row.get("ClientKey") or "").strip()
        if account_id and account_key and client_key:
            result[account_id] = (account_key, client_key)
    return result


def _known_pg_order_ids_v1(account_id: str) -> frozenset[str]:
    with connect() as db:
        rows = db.execute(
            """
            SELECT order_id
            FROM pg_v2_autotrader_execution_requests
            WHERE account_id = ? AND order_id IS NOT NULL
            UNION
            SELECT open_attempt.order_id
            FROM pg_v2_autotrader_live_open_attempts AS open_attempt
            JOIN pg_v2_autotrader_execution_requests AS req
              ON req.request_id = open_attempt.request_id
            WHERE req.account_id = ? AND open_attempt.order_id IS NOT NULL
            UNION
            SELECT close_attempt.order_id
            FROM pg_v2_autotrader_live_close_attempts AS close_attempt
            WHERE close_attempt.account_id = ? AND close_attempt.order_id IS NOT NULL
            """,
            (account_id, account_id, account_id),
        ).fetchall()
    return frozenset(
        str(row["order_id"] if isinstance(row, dict) else row[0]).strip()
        for row in rows
        if str(row["order_id"] if isinstance(row, dict) else row[0]).strip()
    )


def _last_activity_at_v1(account_id: str, *, now: datetime) -> datetime:
    with connect() as db:
        row = db.execute(
            """
            SELECT last_activity_at
            FROM pg_v2_saxo_manual_trade_marker_sync
            WHERE account_id = ?
            """,
            (account_id,),
        ).fetchone()
    if row is None:
        return now - INITIAL_LOOKBACK_V1
    raw = row.get("last_activity_at") if isinstance(row, dict) else row[0]
    if raw is None:
        return now - INITIAL_LOOKBACK_V1
    return max(now - INITIAL_LOOKBACK_V1, _utc(raw) - OVERLAP_V1)


def _direction_v1(value: Any) -> str | None:
    side = str(value or "").strip().lower()
    if side == "buy":
        return "LONG"
    if side == "sell":
        return "SHORT"
    return None


def _positive_float(*values: Any) -> float | None:
    for value in values:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return None


def parse_manual_fill_v1(
    row: Mapping[str, Any],
    *,
    products: Mapping[tuple[int, str], str],
    pg_order_ids: frozenset[str],
) -> ManualSaxoTradeMarkerV1 | None:
    """Return one proven foreign/manual completed fill, otherwise fail closed."""

    if str(row.get("Status") or "").strip() != "FinalFill":
        return None
    substatus = str(row.get("SubStatus") or "").strip()
    if substatus and substatus != "Confirmed":
        return None

    log_id = str(row.get("LogId") or "").strip()
    order_id = str(row.get("OrderId") or "").strip()
    account_id = str(row.get("AccountId") or "").strip()
    asset_type = str(row.get("AssetType") or "").strip()
    position_id = str(row.get("PositionId") or "").strip()
    try:
        uic = int(row.get("Uic"))
    except (TypeError, ValueError):
        return None

    market_name = products.get((uic, asset_type))
    if market_name is None or not log_id or not order_id or not account_id:
        return None
    if order_id in pg_order_ids:
        return None

    direction = _direction_v1(row.get("BuySell"))
    amount = _positive_float(row.get("FilledAmount"), row.get("Amount"), row.get("FillAmount"))
    execution_price = _positive_float(row.get("AveragePrice"), row.get("Price"))
    raw_time = row.get("ActivityTime")
    if direction is None or amount is None or execution_price is None or raw_time is None:
        return None

    return ManualSaxoTradeMarkerV1(
        log_id=log_id,
        account_id=account_id,
        uic=uic,
        asset_type=asset_type,
        market_name=str(market_name),
        order_id=order_id,
        position_id=position_id,
        direction=direction,
        amount=float(amount),
        execution_price=float(execution_price),
        executed_at=_utc(raw_time),
    )


def _persist_marker_v1(marker: ManualSaxoTradeMarkerV1) -> bool:
    with connect() as db:
        existing = db.execute(
            "SELECT 1 FROM pg_v2_saxo_manual_trade_markers WHERE log_id = ?",
            (marker.log_id,),
        ).fetchone()
        if existing is not None:
            return False
        db.execute(
            """
            INSERT INTO pg_v2_saxo_manual_trade_markers(
                log_id, account_id, uic, asset_type, market_name,
                order_id, position_id, direction, amount, execution_price, executed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                marker.log_id,
                marker.account_id,
                marker.uic,
                marker.asset_type,
                marker.market_name,
                marker.order_id,
                marker.position_id,
                marker.direction,
                marker.amount,
                marker.execution_price,
                marker.executed_at,
            ),
        )
    LOGGER.info(
        "Manual Saxo fill captured market=%s direction=%s amount=%s price=%s order_id=%s log_id=%s",
        marker.market_name,
        marker.direction,
        marker.amount,
        marker.execution_price,
        marker.order_id,
        marker.log_id,
    )
    return True


def _persist_sync_state_v1(
    account_id: str,
    *,
    last_activity_at: datetime | None,
    error: str = "",
) -> None:
    with connect() as db:
        db.execute(
            """
            INSERT INTO pg_v2_saxo_manual_trade_marker_sync(
                account_id, last_activity_at, last_success_at, last_error
            ) VALUES (?, ?, CASE WHEN ? = '' THEN now() ELSE NULL END, ?)
            ON CONFLICT (account_id) DO UPDATE SET
                last_activity_at = COALESCE(EXCLUDED.last_activity_at, pg_v2_saxo_manual_trade_marker_sync.last_activity_at),
                last_success_at = CASE
                    WHEN EXCLUDED.last_error = '' THEN now()
                    ELSE pg_v2_saxo_manual_trade_marker_sync.last_success_at
                END,
                last_error = EXCLUDED.last_error
            """,
            (account_id, last_activity_at, error, error),
        )


def sync_manual_saxo_trade_markers_cycle_v1(*, client=None, now: datetime | None = None) -> tuple[int, int]:
    """Poll recent broker order history at low cadence and persist only non-PG FinalFill rows."""

    if not using_postgres():
        return (0, 0)
    ensure_manual_saxo_trade_marker_schema_v1()
    current = _utc(now or datetime.now(timezone.utc))
    products_by_account = _active_products_v1()
    if not products_by_account:
        return (0, 0)

    resolved_client = client or configured_client()
    if resolved_client is None:
        raise RuntimeError("Saxo client is not configured")
    contexts = _account_contexts_v1(resolved_client)

    captured = failed = 0
    for account_id, products in products_by_account.items():
        context = contexts.get(account_id)
        if context is None:
            failed += 1
            _persist_sync_state_v1(account_id, last_activity_at=None, error="ACCOUNT_CONTEXT_UNRESOLVED")
            continue
        account_key, client_key = context
        start = _last_activity_at_v1(account_id, now=current)
        try:
            payload = resolved_client._get(
                "cs/v1/audit/orderactivities",
                params={
                    "AccountKey": account_key,
                    "ClientKey": client_key,
                    "EntryType": "All",
                    "FromDateTime": start.isoformat().replace("+00:00", "Z"),
                    "ToDateTime": current.isoformat().replace("+00:00", "Z"),
                    "$top": 500,
                },
            )
            rows = payload.get("Data") or []
            if not isinstance(rows, list):
                raise RuntimeError("Saxo order activities Data must be a list")
            pg_order_ids = _known_pg_order_ids_v1(account_id)
            latest_seen: datetime | None = None
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                raw_at = row.get("ActivityTime")
                if raw_at is not None:
                    try:
                        observed_at = _utc(raw_at)
                        latest_seen = observed_at if latest_seen is None else max(latest_seen, observed_at)
                    except Exception:
                        pass
                marker = parse_manual_fill_v1(
                    row,
                    products=products,
                    pg_order_ids=pg_order_ids,
                )
                if marker is not None and _persist_marker_v1(marker):
                    captured += 1
            if payload.get("__next"):
                LOGGER.warning(
                    "Manual Saxo marker audit reached page limit account_id=%s; next cycle will overlap safely",
                    account_id,
                )
            _persist_sync_state_v1(
                account_id,
                last_activity_at=latest_seen or current,
                error="",
            )
        except Exception as exc:
            failed += 1
            _persist_sync_state_v1(
                account_id,
                last_activity_at=None,
                error=f"{type(exc).__name__}: {exc}",
            )
            LOGGER.warning(
                "Manual Saxo marker sync failed account_id=%s: %s",
                account_id,
                exc,
                exc_info=True,
            )
    return captured, failed


def run_manual_saxo_trade_markers_forever_v1(
    *,
    interval_seconds: int = DEFAULT_POLL_SECONDS_V1,
) -> None:
    interval = max(30, int(interval_seconds))
    ensure_manual_saxo_trade_marker_schema_v1()
    while True:
        started = time.monotonic()
        try:
            captured, failed = sync_manual_saxo_trade_markers_cycle_v1()
            if captured or failed:
                LOGGER.info(
                    "Manual Saxo marker sync captured=%d failed_accounts=%d",
                    captured,
                    failed,
                )
        except Exception as exc:
            LOGGER.warning("Manual Saxo marker cycle failed: %s", exc, exc_info=True)
        elapsed = time.monotonic() - started
        time.sleep(max(1.0, interval - elapsed))


def load_manual_saxo_trade_markers_v1(market_name: str, *, days: int = 14):
    from autotrader_trade_markers_v1 import AutoTraderTradeMarkerV1

    if not using_postgres():
        return ()
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, int(days)))
    try:
        with connect() as db:
            rows = db.execute(
                """
                SELECT executed_at, execution_price, direction, amount,
                       order_id, position_id
                FROM pg_v2_saxo_manual_trade_markers
                WHERE market_name = ?
                  AND executed_at >= ?
                ORDER BY executed_at ASC
                LIMIT 500
                """,
                (str(market_name), cutoff),
            ).fetchall()
    except Exception:
        # The stream worker owns schema installation. A web deploy may briefly race it.
        return ()

    result = []
    for row in rows:
        values = dict(row) if isinstance(row, dict) else {
            "executed_at": row[0],
            "execution_price": row[1],
            "direction": row[2],
            "amount": row[3],
            "order_id": row[4],
            "position_id": row[5],
        }
        result.append(
            AutoTraderTradeMarkerV1(
                executed_at=_utc(values["executed_at"]),
                execution_price=float(values["execution_price"]),
                direction=str(values["direction"]),
                amount=float(values["amount"]),
                strategy_key="manual-saxo",
                net_position_id=str(values.get("position_id") or values.get("order_id") or ""),
                active=False,
                source="SAXO_MANUAL_FILL",
            )
        )
    return tuple(result)


__all__ = [
    "DEFAULT_POLL_SECONDS_V1",
    "ManualSaxoTradeMarkerV1",
    "ensure_manual_saxo_trade_marker_schema_v1",
    "load_manual_saxo_trade_markers_v1",
    "parse_manual_fill_v1",
    "run_manual_saxo_trade_markers_forever_v1",
    "sync_manual_saxo_trade_markers_cycle_v1",
]
