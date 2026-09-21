from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from threading import Lock
from typing import Any, Mapping, Sequence
from uuid import NAMESPACE_URL, uuid5

import pandas as pd

from autotrader_fast_live_runtime_v2 import (
    DIRECTION_FLAT,
    FastLiveStateV2,
    Macd1mClockV2,
    _exact_product_observation,
    _observed_direction,
)
from autotrader_macd_timeframe_live_v1 import _persist_binary_macd_intent_v1
from autotrader_manage_control_v1 import auto_manage_enabled_v1, position_management_enabled_v1
from autotrader_managed_positions_v1 import is_position_managed_v1
from autotrader_manual_target_v2 import manual_target_pending_v2
from autotrader_pilot_equity_v2 import load_pilot_equity_v2
from autotrader_strategy_enrollment_v2 import (
    EXECUTION_MODE_LIVE,
    StrategyEnrollmentV2,
    load_active_strategy_enrollments_v2,
)
from database import connect, using_postgres


LOGGER = logging.getLogger("pricegauger.autotrader.take_profit_modifier_v1")
_SCHEMA_LOCK = Lock()
_SCHEMA_READY = False

DEFAULT_GIVEBACK_PCT_V1 = 10.0
DEFAULT_MIN_PEAK_PROFIT_PCT_V1 = 0.10
DEFAULT_REENTRY_COOLDOWN_SECONDS_V1 = 30
AMBIGUOUS_EXECUTION_STATUSES_V1 = ("SUBMITTING", "ORDER_ACCEPTED", "UNCERTAIN")


@dataclass(frozen=True, slots=True)
class TakeProfitConfigV1:
    enabled: bool = False
    giveback_pct: float = DEFAULT_GIVEBACK_PCT_V1
    min_peak_profit_pct: float = DEFAULT_MIN_PEAK_PROFIT_PCT_V1
    reentry_cooldown_seconds: int = DEFAULT_REENTRY_COOLDOWN_SECONDS_V1


@dataclass(frozen=True, slots=True)
class TakeProfitDecisionV1:
    high_water_pct: float
    floor_pct: float | None
    armed: bool
    triggered: bool
    giveback_pct: float


@dataclass(frozen=True, slots=True)
class TakeProfitCycleSummaryV1:
    evaluated: int
    armed: int
    triggered: int
    requests_created: int
    blocked_inflight: int
    failed: int


def _utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _validate_config(config: TakeProfitConfigV1) -> TakeProfitConfigV1:
    giveback = float(config.giveback_pct)
    minimum = float(config.min_peak_profit_pct)
    cooldown = int(config.reentry_cooldown_seconds)
    if not 0.0 < giveback < 100.0:
        raise ValueError("giveback_pct must be between 0 and 100")
    if minimum < 0.0:
        raise ValueError("min_peak_profit_pct cannot be negative")
    if cooldown < 0:
        raise ValueError("reentry_cooldown_seconds cannot be negative")
    return TakeProfitConfigV1(
        enabled=bool(config.enabled),
        giveback_pct=giveback,
        min_peak_profit_pct=minimum,
        reentry_cooldown_seconds=cooldown,
    )


def ensure_take_profit_schema_v1() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    if not using_postgres():
        raise RuntimeError("take-profit modifier requires PostgreSQL")
    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return
        with connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS pg_v2_autotrader_take_profit_config (
                    pilot_key TEXT PRIMARY KEY,
                    enabled BOOLEAN NOT NULL DEFAULT FALSE,
                    giveback_pct DOUBLE PRECISION NOT NULL DEFAULT 10.0,
                    min_peak_profit_pct DOUBLE PRECISION NOT NULL DEFAULT 0.10,
                    reentry_cooldown_seconds INTEGER NOT NULL DEFAULT 30,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS pg_v2_autotrader_take_profit_state (
                    pilot_key TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    net_position_id TEXT NOT NULL,
                    uic BIGINT NOT NULL,
                    asset_type TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    amount DOUBLE PRECISION NOT NULL,
                    average_open_price DOUBLE PRECISION NOT NULL,
                    current_pnl_pct DOUBLE PRECISION NOT NULL,
                    high_water_pct DOUBLE PRECISION NOT NULL,
                    floor_pct DOUBLE PRECISION,
                    armed BOOLEAN NOT NULL DEFAULT FALSE,
                    triggered_at TIMESTAMPTZ,
                    intent_event_id UUID,
                    flat_since TIMESTAMPTZ,
                    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS pg_v2_autotrader_take_profit_state_trigger_idx
                ON pg_v2_autotrader_take_profit_state(triggered_at, flat_since)
                """
            )
        _SCHEMA_READY = True


def load_take_profit_config_v1(pilot_key: str) -> TakeProfitConfigV1:
    ensure_take_profit_schema_v1()
    with connect() as db:
        row = db.execute(
            """
            SELECT enabled, giveback_pct, min_peak_profit_pct, reentry_cooldown_seconds
            FROM pg_v2_autotrader_take_profit_config
            WHERE pilot_key = ?
            """,
            (str(pilot_key),),
        ).fetchone()
    if row is None:
        return TakeProfitConfigV1()
    values = dict(row) if isinstance(row, dict) else {
        "enabled": row[0],
        "giveback_pct": row[1],
        "min_peak_profit_pct": row[2],
        "reentry_cooldown_seconds": row[3],
    }
    return _validate_config(
        TakeProfitConfigV1(
            enabled=bool(values["enabled"]),
            giveback_pct=float(values["giveback_pct"]),
            min_peak_profit_pct=float(values["min_peak_profit_pct"]),
            reentry_cooldown_seconds=int(values["reentry_cooldown_seconds"]),
        )
    )


def save_take_profit_config_v1(pilot_key: str, config: TakeProfitConfigV1) -> TakeProfitConfigV1:
    value = _validate_config(config)
    ensure_take_profit_schema_v1()
    with connect() as db:
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_take_profit_config(
                pilot_key, enabled, giveback_pct, min_peak_profit_pct,
                reentry_cooldown_seconds, updated_at
            ) VALUES (?, ?, ?, ?, ?, now())
            ON CONFLICT (pilot_key) DO UPDATE SET
                enabled=EXCLUDED.enabled,
                giveback_pct=EXCLUDED.giveback_pct,
                min_peak_profit_pct=EXCLUDED.min_peak_profit_pct,
                reentry_cooldown_seconds=EXCLUDED.reentry_cooldown_seconds,
                updated_at=now()
            """,
            (
                str(pilot_key),
                bool(value.enabled),
                float(value.giveback_pct),
                float(value.min_peak_profit_pct),
                int(value.reentry_cooldown_seconds),
            ),
        )
        if not value.enabled:
            db.execute(
                "DELETE FROM pg_v2_autotrader_take_profit_state WHERE pilot_key = ?",
                (str(pilot_key),),
            )
    return value


def evaluate_take_profit_v1(
    *,
    current_pnl_pct: float,
    previous_high_water_pct: float | None,
    config: TakeProfitConfigV1,
) -> TakeProfitDecisionV1:
    value = _validate_config(config)
    current = float(current_pnl_pct)
    high = max(current, current if previous_high_water_pct is None else float(previous_high_water_pct))
    armed = bool(value.enabled and high >= float(value.min_peak_profit_pct) and high > 0.0)
    floor = None
    if armed:
        floor = high * (1.0 - (float(value.giveback_pct) / 100.0))
    triggered = bool(armed and floor is not None and current <= floor)
    return TakeProfitDecisionV1(
        high_water_pct=high,
        floor_pct=floor,
        armed=armed,
        triggered=triggered,
        giveback_pct=float(value.giveback_pct),
    )


def _row_dict(row: Any, columns: Sequence[str]) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    return {name: row[index] for index, name in enumerate(columns)}


def _load_state_v1(pilot_key: str) -> dict[str, Any] | None:
    ensure_take_profit_schema_v1()
    columns = (
        "pilot_key", "account_id", "net_position_id", "uic", "asset_type",
        "direction", "amount", "average_open_price", "current_pnl_pct",
        "high_water_pct", "floor_pct", "armed", "triggered_at",
        "intent_event_id", "flat_since", "last_seen_at",
    )
    with connect() as db:
        row = db.execute(
            """
            SELECT pilot_key, account_id, net_position_id, uic, asset_type,
                   direction, amount, average_open_price, current_pnl_pct,
                   high_water_pct, floor_pct, armed, triggered_at,
                   intent_event_id, flat_since, last_seen_at
            FROM pg_v2_autotrader_take_profit_state
            WHERE pilot_key = ?
            """,
            (str(pilot_key),),
        ).fetchone()
    return None if row is None else _row_dict(row, columns)


def load_take_profit_state_v1(pilot_key: str) -> dict[str, Any] | None:
    return _load_state_v1(pilot_key)


def _same_basis_v1(state: Mapping[str, Any], observation: Any) -> bool:
    return (
        str(state.get("account_id") or "") == str(observation.account_id)
        and str(state.get("net_position_id") or "") == str(observation.net_position_id)
        and int(state.get("uic") or -1) == int(observation.uic)
        and str(state.get("asset_type") or "") == str(observation.asset_type)
        and str(state.get("direction") or "").lower() == str(observation.direction).lower()
        and abs(float(state.get("amount") or 0.0) - float(observation.amount)) <= 1e-12
        and abs(float(state.get("average_open_price") or 0.0) - float(observation.average_open_price)) <= 1e-12
    )


def _persist_state_v1(
    enrollment: StrategyEnrollmentV2,
    observation: Any,
    decision: TakeProfitDecisionV1,
    *,
    triggered_at: datetime | None,
    intent_event_id: str | None,
    flat_since: datetime | None,
) -> None:
    with connect() as db:
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_take_profit_state(
                pilot_key, account_id, net_position_id, uic, asset_type,
                direction, amount, average_open_price, current_pnl_pct,
                high_water_pct, floor_pct, armed, triggered_at,
                intent_event_id, flat_since, last_seen_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, now(), now())
            ON CONFLICT (pilot_key) DO UPDATE SET
                account_id=EXCLUDED.account_id,
                net_position_id=EXCLUDED.net_position_id,
                uic=EXCLUDED.uic,
                asset_type=EXCLUDED.asset_type,
                direction=EXCLUDED.direction,
                amount=EXCLUDED.amount,
                average_open_price=EXCLUDED.average_open_price,
                current_pnl_pct=EXCLUDED.current_pnl_pct,
                high_water_pct=EXCLUDED.high_water_pct,
                floor_pct=EXCLUDED.floor_pct,
                armed=EXCLUDED.armed,
                triggered_at=EXCLUDED.triggered_at,
                intent_event_id=EXCLUDED.intent_event_id,
                flat_since=EXCLUDED.flat_since,
                last_seen_at=now(),
                updated_at=now()
            """,
            (
                enrollment.pilot_key,
                observation.account_id,
                observation.net_position_id,
                int(observation.uic),
                observation.asset_type,
                observation.direction,
                float(observation.amount),
                float(observation.average_open_price),
                float(observation.pnl_pct),
                float(decision.high_water_pct),
                None if decision.floor_pct is None else float(decision.floor_pct),
                bool(decision.armed),
                triggered_at,
                intent_event_id,
                flat_since,
            ),
        )


def _ambiguous_execution_inflight_v1(pilot_key: str) -> bool:
    with connect() as db:
        row = db.execute(
            """
            SELECT 1
            FROM pg_v2_autotrader_execution_requests
            WHERE pilot_key = ? AND status IN ('SUBMITTING','ORDER_ACCEPTED','UNCERTAIN')
            LIMIT 1
            """,
            (str(pilot_key),),
        ).fetchone()
    return row is not None


def _take_profit_intent_v1(
    enrollment: StrategyEnrollmentV2,
    observation: Any,
    *,
    event_id: str,
    action_at: datetime,
    signal: str,
) -> FastLiveStateV2:
    observed_direction = _observed_direction(observation)
    return FastLiveStateV2(
        pilot_key=enrollment.pilot_key,
        strategy_key=enrollment.strategy_key,
        desired_direction=DIRECTION_FLAT,
        last_action_at=action_at,
        pending_target_direction=None if observed_direction == DIRECTION_FLAT else DIRECTION_FLAT,
        intent_event_id=event_id,
        intent_signal_at=action_at,
        intent_signal=signal,
        intent_previous_macd=None,
        intent_previous_signal=None,
        intent_current_macd=None,
        intent_current_signal=None,
    )


def _trigger_event_id_v1(enrollment: StrategyEnrollmentV2, observation: Any) -> str:
    identity = (
        f"take-profit-v1|{enrollment.pilot_key}|{observation.account_id}|"
        f"{observation.net_position_id}|{observation.direction}|"
        f"{float(observation.amount):.12g}|{float(observation.average_open_price):.12g}"
    )
    return str(uuid5(NAMESPACE_URL, identity))


def _clear_state_v1(pilot_key: str) -> None:
    with connect() as db:
        db.execute(
            "DELETE FROM pg_v2_autotrader_take_profit_state WHERE pilot_key = ?",
            (str(pilot_key),),
        )


def _mark_flat_since_v1(pilot_key: str, *, now: datetime) -> None:
    with connect() as db:
        db.execute(
            """
            UPDATE pg_v2_autotrader_take_profit_state
            SET flat_since=COALESCE(flat_since, ?), updated_at=now()
            WHERE pilot_key = ? AND triggered_at IS NOT NULL
            """,
            (now, str(pilot_key)),
        )


def take_profit_reentry_blocked_v1(
    enrollment: StrategyEnrollmentV2,
    *,
    observed_direction: str,
    now: datetime | None = None,
) -> bool:
    """Short cooldown after a take-profit FLAT so X cannot instantly churn back in."""

    config = load_take_profit_config_v1(enrollment.pilot_key)
    if not config.enabled or int(config.reentry_cooldown_seconds) <= 0:
        return False
    state = _load_state_v1(enrollment.pilot_key)
    if not state or state.get("triggered_at") is None:
        return False
    current = _utc(now or datetime.now(timezone.utc))
    if str(observed_direction).upper() != DIRECTION_FLAT:
        return False
    flat_since = state.get("flat_since")
    if flat_since is None:
        _mark_flat_since_v1(enrollment.pilot_key, now=current)
        flat_at = current
    else:
        flat_at = _utc(flat_since)
    if current < flat_at + timedelta(seconds=int(config.reentry_cooldown_seconds)):
        return True
    _clear_state_v1(enrollment.pilot_key)
    return False


def run_take_profit_observations_v1(
    observations: Sequence[Any],
    *,
    now: datetime | None = None,
) -> TakeProfitCycleSummaryV1:
    """Evaluate the modifier against already-fetched Saxo observations.

    This function never submits a broker order. It may create the same durable FLAT
    request consumed by the existing hardened strategy close executor.
    """

    if not using_postgres():
        return TakeProfitCycleSummaryV1(0, 0, 0, 0, 0, 0)
    ensure_take_profit_schema_v1()
    current = _utc(now or datetime.now(timezone.utc))
    enrollments = tuple(
        item
        for item in load_active_strategy_enrollments_v2()
        if item.enabled and item.execution_mode == EXECUTION_MODE_LIVE
    )

    evaluated = armed = triggered = requests_created = blocked_inflight = failed = 0
    for enrollment in enrollments:
        try:
            config = load_take_profit_config_v1(enrollment.pilot_key)
            if not config.enabled:
                continue
            if not position_management_enabled_v1(enrollment) or not auto_manage_enabled_v1(enrollment):
                continue

            observation = _exact_product_observation(enrollment, tuple(observations))
            if observation is None:
                state = _load_state_v1(enrollment.pilot_key)
                if state and state.get("triggered_at") is not None:
                    _mark_flat_since_v1(enrollment.pilot_key, now=current)
                else:
                    _clear_state_v1(enrollment.pilot_key)
                continue
            if not is_position_managed_v1(observation):
                continue

            evaluated += 1
            previous = _load_state_v1(enrollment.pilot_key)
            same_basis = bool(previous and _same_basis_v1(previous, observation))
            previous_high = float(previous["high_water_pct"]) if same_basis else None
            previous_triggered_at = _utc(previous["triggered_at"]) if same_basis and previous.get("triggered_at") else None
            previous_event_id = str(previous["intent_event_id"]) if same_basis and previous.get("intent_event_id") else None

            decision = evaluate_take_profit_v1(
                current_pnl_pct=float(observation.pnl_pct),
                previous_high_water_pct=previous_high,
                config=config,
            )
            if decision.armed:
                armed += 1

            trigger_at = previous_triggered_at
            event_id = previous_event_id
            if decision.triggered or trigger_at is not None:
                triggered += 1
                if trigger_at is None:
                    trigger_at = current
                    event_id = _trigger_event_id_v1(enrollment, observation)
                    LOGGER.warning(
                        "TAKE_PROFIT trigger pilot=%s strategy=%s position=%s pnl=%.4f%% peak=%.4f%% floor=%.4f%% giveback=%.2f%%",
                        enrollment.pilot_key,
                        enrollment.strategy_key,
                        observation.net_position_id,
                        observation.pnl_pct,
                        decision.high_water_pct,
                        decision.floor_pct if decision.floor_pct is not None else float("nan"),
                        config.giveback_pct,
                    )

                _persist_state_v1(
                    enrollment,
                    observation,
                    decision,
                    triggered_at=trigger_at,
                    intent_event_id=event_id,
                    flat_since=None,
                )

                if manual_target_pending_v2(enrollment.pilot_key) or _ambiguous_execution_inflight_v1(enrollment.pilot_key):
                    blocked_inflight += 1
                    continue

                signal = (
                    f"TAKE_PROFIT_GIVEBACK:peak={decision.high_water_pct:.6f};"
                    f"floor={float(decision.floor_pct or 0.0):.6f};"
                    f"current={float(observation.pnl_pct):.6f};"
                    f"giveback={config.giveback_pct:.3f};"
                    f"min_peak={config.min_peak_profit_pct:.6f}"
                )
                intent = _take_profit_intent_v1(
                    enrollment,
                    observation,
                    event_id=str(event_id),
                    action_at=trigger_at,
                    signal=signal,
                )
                equity = load_pilot_equity_v2(pilot_key=enrollment.pilot_key)
                created = _persist_binary_macd_intent_v1(
                    enrollment=enrollment,
                    state=intent,
                    observed=observation,
                    observed_direction=_observed_direction(observation),
                    budget_amount=float(equity.entry_budget),
                    budget_currency=str(equity.currency),
                    supersede_prior=previous_triggered_at is None,
                )
                requests_created += int(bool(created))
            else:
                _persist_state_v1(
                    enrollment,
                    observation,
                    decision,
                    triggered_at=None,
                    intent_event_id=None,
                    flat_since=None,
                )
        except Exception as exc:
            failed += 1
            LOGGER.warning(
                "TAKE_PROFIT evaluation failed pilot=%s strategy=%s: %s",
                enrollment.pilot_key,
                enrollment.strategy_key,
                exc,
                exc_info=True,
            )

    if triggered or requests_created or blocked_inflight or failed:
        LOGGER.info(
            "TAKE_PROFIT summary evaluated=%d armed=%d triggered=%d requests=%d blocked_inflight=%d failed=%d",
            evaluated, armed, triggered, requests_created, blocked_inflight, failed,
        )
    return TakeProfitCycleSummaryV1(
        evaluated=evaluated,
        armed=armed,
        triggered=triggered,
        requests_created=requests_created,
        blocked_inflight=blocked_inflight,
        failed=failed,
    )


def apply_take_profit_replay_v1(
    frame: pd.DataFrame,
    *,
    giveback_pct: float = DEFAULT_GIVEBACK_PCT_V1,
    min_peak_profit_pct: float = DEFAULT_MIN_PEAK_PROFIT_PCT_V1,
) -> pd.DataFrame:
    """Wrap any PRICE/TARGET strategy with the same peak-profit giveback contract.

    After a take-profit exit, the replay remains FLAT while the base target stays in
    the same direction. A base target change releases the latch.
    """

    if "PRICE" not in frame.columns or "TARGET" not in frame.columns:
        raise ValueError("take-profit replay requires PRICE and TARGET columns")
    config = _validate_config(
        TakeProfitConfigV1(
            enabled=True,
            giveback_pct=float(giveback_pct),
            min_peak_profit_pct=float(min_peak_profit_pct),
            reentry_cooldown_seconds=0,
        )
    )
    result = frame.copy()
    raw = result["TARGET"].fillna(0.0).astype("int64")
    price = result["PRICE"].astype("float64")

    managed = 0
    entry_price: float | None = None
    high_water = 0.0
    locked_direction = 0
    targets: list[int] = []
    peak_values: list[float] = []
    floor_values: list[float | None] = []
    reasons: list[str] = []

    for index in range(len(result)):
        base = int(raw.iloc[index])
        current_price = float(price.iloc[index])
        reason = "follow_base"

        if locked_direction:
            if base == locked_direction:
                managed = 0
                entry_price = None
                high_water = 0.0
                targets.append(0)
                peak_values.append(0.0)
                floor_values.append(None)
                reasons.append("take_profit_latched")
                continue
            locked_direction = 0

        if base not in (-1, 0, 1):
            base = 0

        if base != managed:
            managed = base
            entry_price = current_price if managed in (-1, 1) else None
            high_water = 0.0
            reason = "base_change"

        floor: float | None = None
        if managed in (-1, 1) and entry_price is not None and entry_price > 0.0:
            pnl = managed * ((current_price / entry_price) - 1.0) * 100.0
            high_water = max(high_water, pnl)
            decision = evaluate_take_profit_v1(
                current_pnl_pct=pnl,
                previous_high_water_pct=high_water,
                config=config,
            )
            high_water = decision.high_water_pct
            floor = decision.floor_pct
            if decision.triggered:
                locked_direction = managed
                managed = 0
                entry_price = None
                reason = "take_profit"

        targets.append(managed)
        peak_values.append(high_water)
        floor_values.append(floor)
        reasons.append(reason)

    result["RAW_TARGET"] = raw.astype("float64")
    result["TARGET"] = pd.Series(targets, index=result.index, dtype="float64")
    result["TAKE_PROFIT_PEAK_PCT"] = pd.Series(peak_values, index=result.index, dtype="float64")
    result["TAKE_PROFIT_FLOOR_PCT"] = pd.Series(floor_values, index=result.index, dtype="float64")
    result["TAKE_PROFIT_REASON"] = reasons
    return result


__all__ = [
    "DEFAULT_GIVEBACK_PCT_V1",
    "DEFAULT_MIN_PEAK_PROFIT_PCT_V1",
    "DEFAULT_REENTRY_COOLDOWN_SECONDS_V1",
    "TakeProfitConfigV1",
    "TakeProfitCycleSummaryV1",
    "TakeProfitDecisionV1",
    "apply_take_profit_replay_v1",
    "ensure_take_profit_schema_v1",
    "evaluate_take_profit_v1",
    "load_take_profit_config_v1",
    "load_take_profit_state_v1",
    "run_take_profit_observations_v1",
    "save_take_profit_config_v1",
    "take_profit_reentry_blocked_v1",
]
