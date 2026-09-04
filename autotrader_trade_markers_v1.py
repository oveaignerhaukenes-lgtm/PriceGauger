from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from autotrader_schema_v2 import ensure_autotrader_schema_v2
from database import connect, using_postgres


_SCHEMA_LOCK = Lock()
_SCHEMA_READY = False


@dataclass(frozen=True, slots=True)
class AutoTraderTradeMarkerV1:
    executed_at: datetime
    execution_price: float
    direction: str
    amount: float
    strategy_key: str
    net_position_id: str
    active: bool
    source: str


def _utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _value(row: Any, key: str, index: int):
    if isinstance(row, dict):
        return row.get(key)
    try:
        return row[key]
    except Exception:
        return row[index]


def _direction(value: Any) -> str:
    normalized = str(value or "").strip().upper()
    if normalized in {"BUY", "LONG"}:
        return "LONG"
    if normalized in {"SELL", "SHORT"}:
        return "SHORT"
    raise ValueError(f"unsupported trade-marker direction: {value}")


def ensure_autotrader_trade_marker_schema_v1() -> None:
    """Create the durable OPEN-marker projection from the runtime, never from UI rendering."""
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    if not using_postgres():
        return
    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return
        ensure_autotrader_schema_v2()
        with connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS pg_v2_autotrader_trade_markers (
                    request_id UUID PRIMARY KEY REFERENCES pg_v2_autotrader_execution_requests(request_id),
                    pilot_key TEXT NOT NULL,
                    strategy_key TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    net_position_id TEXT NOT NULL,
                    uic BIGINT NOT NULL,
                    asset_type TEXT NOT NULL,
                    market_id BIGINT NOT NULL,
                    instrument_id BIGINT NOT NULL,
                    direction TEXT NOT NULL CHECK (direction IN ('LONG', 'SHORT')),
                    amount DOUBLE PRECISION NOT NULL CHECK (amount > 0),
                    execution_price DOUBLE PRECISION NOT NULL CHECK (execution_price > 0),
                    executed_at TIMESTAMPTZ NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS pg_v2_autotrader_trade_markers_product_time_idx
                ON pg_v2_autotrader_trade_markers(account_id, uic, asset_type, executed_at DESC)
                """
            )
            db.execute(
                """
                CREATE OR REPLACE FUNCTION pg_v2_capture_autotrader_open_marker()
                RETURNS trigger AS $$
                BEGIN
                    IF NEW.status = 'RECONCILED' AND OLD.status IS DISTINCT FROM 'RECONCILED' THEN
                        INSERT INTO pg_v2_autotrader_trade_markers(
                            request_id, pilot_key, strategy_key, account_id,
                            net_position_id, uic, asset_type, market_id, instrument_id,
                            direction, amount, execution_price, executed_at
                        )
                        SELECT
                            req.request_id,
                            req.pilot_key,
                            req.strategy_key,
                            req.account_id,
                            managed.net_position_id,
                            req.uic,
                            req.asset_type,
                            req.market_id,
                            req.instrument_id,
                            req.desired_direction,
                            managed.amount,
                            managed.average_open_price,
                            NEW.updated_at
                        FROM pg_v2_autotrader_execution_requests AS req
                        JOIN LATERAL (
                            SELECT net_position_id, amount, average_open_price
                            FROM pg_v2_autotrader_managed_positions
                            WHERE account_id = req.account_id
                              AND uic = req.uic
                              AND asset_type = req.asset_type
                              AND managed = TRUE
                            ORDER BY enrolled_at DESC
                            LIMIT 1
                        ) AS managed ON TRUE
                        WHERE req.request_id = NEW.request_id
                          AND req.action = 'OPEN'
                          AND req.desired_direction IN ('LONG', 'SHORT')
                        ON CONFLICT (request_id) DO NOTHING;
                    END IF;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql
                """
            )
            db.execute(
                "DROP TRIGGER IF EXISTS pg_v2_autotrader_open_marker_trigger ON pg_v2_autotrader_live_open_attempts"
            )
            db.execute(
                """
                CREATE TRIGGER pg_v2_autotrader_open_marker_trigger
                AFTER UPDATE OF status ON pg_v2_autotrader_live_open_attempts
                FOR EACH ROW
                EXECUTE FUNCTION pg_v2_capture_autotrader_open_marker()
                """
            )
        _SCHEMA_READY = True


def _historical_markers_v1(market_name: str) -> tuple[AutoTraderTradeMarkerV1, ...]:
    if not using_postgres():
        return ()
    try:
        with connect() as db:
            rows = db.execute(
                """
                SELECT marker.executed_at, marker.execution_price, marker.direction,
                       marker.amount, marker.strategy_key, marker.net_position_id,
                       CASE WHEN managed.net_position_id IS NULL THEN FALSE ELSE TRUE END AS active
                FROM pg_v2_autotrader_trade_markers AS marker
                JOIN pg_v2_autotrader_strategy_enrollments AS enrollment
                  ON enrollment.pilot_key = marker.pilot_key
                LEFT JOIN pg_v2_autotrader_managed_positions AS managed
                  ON managed.account_id = marker.account_id
                 AND managed.net_position_id = marker.net_position_id
                 AND managed.uic = marker.uic
                 AND managed.asset_type = marker.asset_type
                 AND managed.managed = TRUE
                WHERE enrollment.market_name = ?
                  AND marker.executed_at >= now() - INTERVAL '14 days'
                ORDER BY marker.executed_at ASC
                LIMIT 500
                """,
                (str(market_name),),
            ).fetchall()
    except Exception:
        # A web instance may race the worker that installs this new read projection.
        return ()

    result: list[AutoTraderTradeMarkerV1] = []
    for row in rows:
        result.append(
            AutoTraderTradeMarkerV1(
                executed_at=_utc(_value(row, "executed_at", 0)),
                execution_price=float(_value(row, "execution_price", 1)),
                direction=_direction(_value(row, "direction", 2)),
                amount=float(_value(row, "amount", 3)),
                strategy_key=str(_value(row, "strategy_key", 4) or ""),
                net_position_id=str(_value(row, "net_position_id", 5) or ""),
                active=bool(_value(row, "active", 6)),
                source="AUTOTRADER_OPEN",
            )
        )
    return tuple(result)


def _active_managed_marker_v1(market_name: str) -> AutoTraderTradeMarkerV1 | None:
    if not using_postgres():
        return None
    try:
        with connect() as db:
            row = db.execute(
                """
                SELECT managed.enrolled_at, managed.average_open_price, managed.direction,
                       managed.amount, enrollment.strategy_key, managed.net_position_id
                FROM pg_v2_autotrader_managed_positions AS managed
                JOIN pg_v2_autotrader_strategy_enrollments AS enrollment
                  ON enrollment.account_id = managed.account_id
                 AND enrollment.uic = managed.uic
                 AND enrollment.asset_type = managed.asset_type
                 AND enrollment.enabled = TRUE
                 AND enrollment.execution_mode = 'LIVE_MANAGE'
                WHERE enrollment.market_name = ? AND managed.managed = TRUE
                ORDER BY managed.enrolled_at DESC
                LIMIT 1
                """,
                (str(market_name),),
            ).fetchone()
    except Exception:
        return None
    if row is None:
        return None
    return AutoTraderTradeMarkerV1(
        executed_at=_utc(_value(row, "enrolled_at", 0)),
        execution_price=float(_value(row, "average_open_price", 1)),
        direction=_direction(_value(row, "direction", 2)),
        amount=float(_value(row, "amount", 3)),
        strategy_key=str(_value(row, "strategy_key", 4) or ""),
        net_position_id=str(_value(row, "net_position_id", 5) or ""),
        active=True,
        source="ACTIVE_MANAGED_POSITION",
    )


def load_autotrader_trade_markers_v1(market_name: str) -> tuple[AutoTraderTradeMarkerV1, ...]:
    """Return reconciled PG entries plus an exact active-position fallback.

    Historical triangles come only from reconciled AutoTrader OPEN requests. The fallback
    exists so a position that predates this projection is still visibly marked as active;
    it is not silently rewritten as historical AutoTrader execution.
    """
    historical = list(_historical_markers_v1(market_name))
    active = _active_managed_marker_v1(market_name)
    if active is None:
        return tuple(historical)

    matched = False
    for index, marker in enumerate(historical):
        if marker.net_position_id != active.net_position_id:
            continue
        historical[index] = AutoTraderTradeMarkerV1(
            executed_at=marker.executed_at,
            execution_price=marker.execution_price,
            direction=marker.direction,
            amount=marker.amount,
            strategy_key=marker.strategy_key,
            net_position_id=marker.net_position_id,
            active=True,
            source=marker.source,
        )
        matched = True
        break
    if not matched:
        historical.append(active)
    return tuple(historical)


__all__ = [
    "AutoTraderTradeMarkerV1",
    "ensure_autotrader_trade_marker_schema_v1",
    "load_autotrader_trade_markers_v1",
]
