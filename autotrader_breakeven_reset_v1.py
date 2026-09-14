from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

from database import connect, using_postgres


DirectionV1 = Literal["LONG", "SHORT"]
ACTION_HOLD = "HOLD"
ACTION_CLOSE = "CLOSE"
REASON_BREAKEVEN_RESET = "BREAKEVEN_RESET"
DEFAULT_COOLDOWN_SECONDS = 60
DEFAULT_MIN_FAVOURABLE_BPS = 2.0
DEFAULT_BREAKEVEN_BAND_BPS = 1.0
_SCHEMA_LOCK = Lock()
_SCHEMA_READY = False


@dataclass(frozen=True, slots=True)
class BreakevenResetConfigV1:
    enabled: bool = True
    cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS
    min_favourable_bps: float = DEFAULT_MIN_FAVOURABLE_BPS
    breakeven_band_bps: float = DEFAULT_BREAKEVEN_BAND_BPS


@dataclass(frozen=True, slots=True)
class BreakevenResetStateV1:
    entry_price: float
    direction: DirectionV1
    profit_armed: bool = False
    favourable_extreme: float | None = None
    cooldown_until: datetime | None = None


@dataclass(frozen=True, slots=True)
class BreakevenResetDecisionV1:
    action: str
    state: BreakevenResetStateV1
    reason: str


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _row_dict(row: Any) -> dict[str, Any]:
    return dict(row) if not isinstance(row, dict) else row


def _bps(entry: float, price: float, direction: DirectionV1) -> float:
    if entry <= 0.0:
        raise ValueError("entry_price must be positive")
    raw = (float(price) - float(entry)) / float(entry) * 10000.0
    return raw if direction == "LONG" else -raw


def _validate_config(config: BreakevenResetConfigV1) -> BreakevenResetConfigV1:
    if int(config.cooldown_seconds) < 1:
        raise ValueError("cooldown_seconds must be at least 1")
    if float(config.min_favourable_bps) < 0.0:
        raise ValueError("min_favourable_bps cannot be negative")
    if float(config.breakeven_band_bps) < 0.0:
        raise ValueError("breakeven_band_bps cannot be negative")
    return config


def ensure_breakeven_reset_schema_v1() -> None:
    """Runtime-owned additive schema for the global AutoManage reset policy."""
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    if not using_postgres():
        raise RuntimeError("breakeven reset requires PostgreSQL")
    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return
        with connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS pg_v2_autotrader_breakeven_reset_config (
                    config_id SMALLINT PRIMARY KEY CHECK (config_id = 1),
                    enabled BOOLEAN NOT NULL DEFAULT TRUE,
                    cooldown_seconds INTEGER NOT NULL DEFAULT 60 CHECK (cooldown_seconds >= 1),
                    min_favourable_bps DOUBLE PRECISION NOT NULL DEFAULT 2.0 CHECK (min_favourable_bps >= 0),
                    breakeven_band_bps DOUBLE PRECISION NOT NULL DEFAULT 1.0 CHECK (breakeven_band_bps >= 0),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            db.execute(
                """
                INSERT INTO pg_v2_autotrader_breakeven_reset_config(
                    config_id, enabled, cooldown_seconds,
                    min_favourable_bps, breakeven_band_bps
                ) VALUES (1, TRUE, 60, 2.0, 1.0)
                ON CONFLICT (config_id) DO NOTHING
                """
            )
        _SCHEMA_READY = True


def load_breakeven_reset_config_v1() -> BreakevenResetConfigV1:
    with connect() as db:
        row = db.execute(
            """
            SELECT enabled, cooldown_seconds, min_favourable_bps, breakeven_band_bps
            FROM pg_v2_autotrader_breakeven_reset_config
            WHERE config_id = 1
            """
        ).fetchone()
    if row is None:
        return BreakevenResetConfigV1()
    item = _row_dict(row)
    return _validate_config(
        BreakevenResetConfigV1(
            enabled=bool(item["enabled"]),
            cooldown_seconds=int(item["cooldown_seconds"]),
            min_favourable_bps=float(item["min_favourable_bps"]),
            breakeven_band_bps=float(item["breakeven_band_bps"]),
        )
    )


def save_breakeven_reset_config_v1(config: BreakevenResetConfigV1) -> BreakevenResetConfigV1:
    config = _validate_config(config)
    with connect() as db:
        db.execute(
            """
            UPDATE pg_v2_autotrader_breakeven_reset_config
            SET enabled = ?, cooldown_seconds = ?, min_favourable_bps = ?,
                breakeven_band_bps = ?, updated_at = now()
            WHERE config_id = 1
            """,
            (
                bool(config.enabled),
                int(config.cooldown_seconds),
                float(config.min_favourable_bps),
                float(config.breakeven_band_bps),
            ),
        )
    return config


def evaluate_breakeven_reset_v1(
    state: BreakevenResetStateV1,
    *,
    price: float,
    now: datetime,
    config: BreakevenResetConfigV1 = BreakevenResetConfigV1(),
) -> BreakevenResetDecisionV1:
    """Global AutoManage policy: bank a round trip to breakeven, then reassess.

    The guard only arms after the position has first travelled favourably by the
    configured amount. It therefore cannot close a fresh entry merely because spread
    places the first quote around entry. Once armed, a return into/beyond the
    breakeven band requests CLOSE. Re-entry authority is intentionally separate.
    """
    config = _validate_config(config)
    now = _utc(now)
    if not config.enabled:
        return BreakevenResetDecisionV1(ACTION_HOLD, state, "disabled")
    if state.direction not in {"LONG", "SHORT"}:
        raise ValueError("direction must be LONG or SHORT")
    if price <= 0.0:
        raise ValueError("price must be positive")

    favourable = _bps(state.entry_price, price, state.direction)
    extreme = favourable if state.favourable_extreme is None else max(state.favourable_extreme, favourable)
    armed = bool(state.profit_armed or extreme >= float(config.min_favourable_bps))
    updated = BreakevenResetStateV1(
        entry_price=state.entry_price,
        direction=state.direction,
        profit_armed=armed,
        favourable_extreme=extreme,
        cooldown_until=state.cooldown_until,
    )
    if not armed:
        return BreakevenResetDecisionV1(ACTION_HOLD, updated, "waiting for profit-zone arm")

    if favourable <= float(config.breakeven_band_bps):
        until = now + timedelta(seconds=int(config.cooldown_seconds))
        closed = BreakevenResetStateV1(
            entry_price=state.entry_price,
            direction=state.direction,
            profit_armed=True,
            favourable_extreme=extreme,
            cooldown_until=until,
        )
        return BreakevenResetDecisionV1(
            ACTION_CLOSE,
            closed,
            f"{REASON_BREAKEVEN_RESET} favourable_bps={favourable:.3f} cooldown_until={until.isoformat()}",
        )
    return BreakevenResetDecisionV1(ACTION_HOLD, updated, "profit remains above breakeven band")


def breakeven_reset_due_from_returns_v1(
    *,
    pnl_pct: float,
    high_water_pct: float,
    config: BreakevenResetConfigV1,
) -> bool:
    config = _validate_config(config)
    if not config.enabled:
        return False
    min_profit_pct = float(config.min_favourable_bps) / 100.0
    band_pct = float(config.breakeven_band_bps) / 100.0
    return float(high_water_pct) >= min_profit_pct and float(pnl_pct) <= band_pct


def materialize_breakeven_reset_triggers_v1() -> int:
    """Promote eligible managed positions into the existing hardened close pipeline."""
    if not using_postgres():
        return 0
    ensure_breakeven_reset_schema_v1()
    config = load_breakeven_reset_config_v1()
    if not config.enabled:
        return 0
    min_profit_pct = float(config.min_favourable_bps) / 100.0
    band_pct = float(config.breakeven_band_bps) / 100.0
    with connect() as db:
        rows = db.execute(
            """
            SELECT state.account_id, state.net_position_id, state.uic, state.asset_type,
                   state.direction, state.pnl_pct, state.high_water_pct,
                   state.trailing_floor_pct, state.price_delay_minutes,
                   state.average_open_price,
                   risk.hard_stop_pct, risk.trailing_activation_pct,
                   risk.trailing_drawdown_pct, risk.fixed_take_profit_pct
            FROM pg_v2_autotrader_risk_state AS state
            JOIN pg_v2_autotrader_managed_positions AS managed
              ON managed.account_id = state.account_id
             AND managed.net_position_id = state.net_position_id
             AND managed.managed = TRUE
             AND managed.uic = state.uic
             AND managed.asset_type = state.asset_type
             AND LOWER(managed.direction) = LOWER(state.direction)
             AND ABS(managed.average_open_price - state.average_open_price) <= 1e-12
            CROSS JOIN pg_v2_autotrader_risk_config AS risk
            WHERE risk.config_id = 1
              AND state.active = TRUE
              AND state.triggered_reason IS NULL
              AND state.high_water_pct >= ?
              AND state.pnl_pct <= ?
            ORDER BY state.last_seen_at ASC
            """,
            (min_profit_pct, band_pct),
        ).fetchall()
        created = 0
        now = datetime.now(timezone.utc)
        for row in rows:
            item = _row_dict(row)
            event_id = str(
                uuid5(
                    NAMESPACE_URL,
                    "|".join(
                        (
                            REASON_BREAKEVEN_RESET,
                            str(item["account_id"]),
                            str(item["net_position_id"]),
                            str(item["direction"]),
                            f"{float(item['average_open_price']):.12g}",
                        )
                    ),
                )
            )
            db.execute(
                """
                INSERT INTO pg_v2_autotrader_risk_events(
                    event_id, account_id, net_position_id, uic, asset_type, direction,
                    reason, pnl_pct, high_water_pct, trailing_floor_pct,
                    hard_stop_pct, trailing_activation_pct, trailing_drawdown_pct,
                    fixed_take_profit_pct, price_delay_minutes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (event_id) DO NOTHING
                """,
                (
                    event_id,
                    str(item["account_id"]),
                    str(item["net_position_id"]),
                    int(item["uic"]),
                    str(item["asset_type"]),
                    str(item["direction"]),
                    REASON_BREAKEVEN_RESET,
                    float(item["pnl_pct"]),
                    float(item["high_water_pct"]),
                    None if item.get("trailing_floor_pct") is None else float(item["trailing_floor_pct"]),
                    float(item["hard_stop_pct"]),
                    float(item["trailing_activation_pct"]),
                    float(item["trailing_drawdown_pct"]),
                    float(item["fixed_take_profit_pct"]),
                    int(item["price_delay_minutes"]),
                ),
            )
            updated = db.execute(
                """
                UPDATE pg_v2_autotrader_risk_state
                SET triggered_reason = ?, triggered_at = ?,
                    last_action = 'WOULD_CLOSE', last_reason = ?, updated_at = now()
                WHERE account_id = ? AND net_position_id = ?
                  AND active = TRUE AND triggered_reason IS NULL
                """,
                (
                    REASON_BREAKEVEN_RESET,
                    now,
                    REASON_BREAKEVEN_RESET,
                    str(item["account_id"]),
                    str(item["net_position_id"]),
                ),
            )
            created += int(getattr(updated, "rowcount", 0) or 0)
    return created


def breakeven_trigger_still_valid_v1(
    *,
    pnl_pct: float,
    high_water_pct: float,
    config: BreakevenResetConfigV1 | None = None,
) -> bool:
    active = load_breakeven_reset_config_v1() if config is None else config
    return breakeven_reset_due_from_returns_v1(
        pnl_pct=float(pnl_pct),
        high_water_pct=float(high_water_pct),
        config=active,
    )


def latest_breakeven_cooldown_until_v1(
    *,
    pilot_key: str,
    account_id: str,
    uic: int,
    asset_type: str,
) -> datetime | None:
    ensure_breakeven_reset_schema_v1()
    config = load_breakeven_reset_config_v1()
    if not config.enabled:
        return None
    with connect() as db:
        row = db.execute(
            """
            SELECT rec.reconciled_at
            FROM pg_v2_autotrader_risk_events AS event
            JOIN pg_v2_autotrader_live_close_attempts AS close
              ON close.event_id = event.event_id AND close.status = 'RECONCILED'
            JOIN pg_v2_autotrader_equity_reconciliations AS rec
              ON rec.close_event_id = close.event_id
            WHERE event.reason = ?
              AND event.account_id = ? AND event.uic = ? AND event.asset_type = ?
              AND rec.pilot_key = ?
            ORDER BY rec.reconciled_at DESC
            LIMIT 1
            """,
            (REASON_BREAKEVEN_RESET, str(account_id), int(uic), str(asset_type), str(pilot_key)),
        ).fetchone()
    if row is None:
        return None
    item = _row_dict(row)
    reconciled_at = item["reconciled_at"]
    if not isinstance(reconciled_at, datetime):
        reconciled_at = datetime.fromisoformat(str(reconciled_at).replace("Z", "+00:00"))
    return _utc(reconciled_at) + timedelta(seconds=int(config.cooldown_seconds))


def require_breakeven_reentry_allowed_v1(
    *,
    pilot_key: str,
    account_id: str,
    uic: int,
    asset_type: str,
    now: datetime | None = None,
) -> None:
    current = datetime.now(timezone.utc) if now is None else _utc(now)
    until = latest_breakeven_cooldown_until_v1(
        pilot_key=pilot_key,
        account_id=account_id,
        uic=uic,
        asset_type=asset_type,
    )
    if until is not None and current < until:
        remaining = max(1, int((until - current).total_seconds() + 0.999))
        raise ValueError(f"BREAKEVEN_RESET_COOLDOWN:{remaining}s")


def reentry_allowed_v1(*, cooldown_until: datetime | None, now: datetime) -> bool:
    if cooldown_until is None:
        return True
    return _utc(now) >= _utc(cooldown_until)


__all__ = [
    "ACTION_CLOSE",
    "ACTION_HOLD",
    "BreakevenResetConfigV1",
    "BreakevenResetDecisionV1",
    "BreakevenResetStateV1",
    "DEFAULT_BREAKEVEN_BAND_BPS",
    "DEFAULT_COOLDOWN_SECONDS",
    "DEFAULT_MIN_FAVOURABLE_BPS",
    "REASON_BREAKEVEN_RESET",
    "breakeven_reset_due_from_returns_v1",
    "breakeven_trigger_still_valid_v1",
    "ensure_breakeven_reset_schema_v1",
    "evaluate_breakeven_reset_v1",
    "latest_breakeven_cooldown_until_v1",
    "load_breakeven_reset_config_v1",
    "materialize_breakeven_reset_triggers_v1",
    "reentry_allowed_v1",
    "require_breakeven_reentry_allowed_v1",
    "save_breakeven_reset_config_v1",
]
