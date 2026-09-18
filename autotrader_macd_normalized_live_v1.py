from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from autotrader_fast_live_runtime_v2 import (
    DIRECTION_FLAT,
    DIRECTION_LONG,
    DIRECTION_SHORT,
    FRESH_MAX_AGE,
    FastLiveCycleV2,
    FastLiveStateV2,
    Macd1mClockV2,
    _clear_intent_v2,
    _exact_product_observation,
    _new_intent_state_v2,
    _observed_direction,
    _persist_bootstrap_v2,
    _persist_intent_and_request_v2,
    _persist_state_v2,
    ensure_fast_live_schema_v2,
    load_fast_live_state_v2,
)
from autotrader_macd_supervisor_normalized_replay_v1 import replay_normalized_macd_supervisor_v1
from autotrader_macd_supervisor_replay_v1 import SUPERVISOR_WARMUP_1M_ROWS_V1
from autotrader_macd_timeframe_live_v1 import MACD_WARMUP_LOOKBACK_V1, MACD_WARMUP_MAX_BARS_V1
from autotrader_pilot_equity_v2 import load_pilot_equity_v2
from autotrader_position_manager_replay_v1 import DEFAULT_POSITION_MANAGER_CONFIG_V1
from autotrader_risk_control_v2 import PositionObservationV2, _position_observations_v2
from autotrader_strategy_catalog_v2 import MACD_NORM_MANAGER_STRATEGY_V1, MACD_NORM_STRATEGY_V1
from autotrader_strategy_enrollment_v2 import EXECUTION_MODE_LIVE, StrategyEnrollmentV2
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2, CanonicalMarketBarV2
from database import connect
from saxo_provider import configured_client


MACD_NORMALIZED_LIVE_STRATEGIES_V1 = {
    MACD_NORM_STRATEGY_V1,
    MACD_NORM_MANAGER_STRATEGY_V1,
}
MAX_LIVE_GAP_MINUTES_V1 = 2.0


@dataclass(frozen=True, slots=True)
class NormalizedManagerLiveStateV1:
    pilot_key: str
    strategy_key: str
    direction: str
    active_bars: int = 0
    mfe_pct: float = 0.0
    cooldown_remaining: int = 0
    blocked_reentry_direction: str | None = None
    reentry_count: int = 0
    last_action_at: datetime | None = None


def _utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _bar_action_at(bar: CanonicalMarketBarV2) -> datetime:
    return _utc(bar.bar_time).replace(second=0, microsecond=0) + timedelta(minutes=1)


def _direction_from_target(value: float) -> str:
    number = float(value)
    if number > 0.0:
        return DIRECTION_LONG
    if number < 0.0:
        return DIRECTION_SHORT
    return DIRECTION_FLAT


def ensure_macd_normalized_live_schema_v1() -> None:
    ensure_fast_live_schema_v2()
    with connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pg_v2_autotrader_macd_norm_manager_state (
                pilot_key TEXT PRIMARY KEY REFERENCES pg_v2_autotrader_strategy_enrollments(pilot_key),
                strategy_key TEXT NOT NULL,
                direction TEXT NOT NULL CHECK (direction IN ('FLAT','LONG','SHORT')),
                active_bars INTEGER NOT NULL DEFAULT 0,
                mfe_pct DOUBLE PRECISION NOT NULL DEFAULT 0.0,
                cooldown_remaining INTEGER NOT NULL DEFAULT 0,
                blocked_reentry_direction TEXT CHECK (
                    blocked_reentry_direction IS NULL
                    OR blocked_reentry_direction IN ('LONG','SHORT')
                ),
                reentry_count INTEGER NOT NULL DEFAULT 0,
                last_action_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )


def _load_manager_state_v1(enrollment: StrategyEnrollmentV2) -> NormalizedManagerLiveStateV1 | None:
    ensure_macd_normalized_live_schema_v1()
    with connect() as db:
        row = db.execute(
            """
            SELECT strategy_key, direction, active_bars, mfe_pct, cooldown_remaining,
                   blocked_reentry_direction, reentry_count, last_action_at
            FROM pg_v2_autotrader_macd_norm_manager_state
            WHERE pilot_key = ?
            """,
            (enrollment.pilot_key,),
        ).fetchone()
    if row is None:
        return None
    values = dict(row) if isinstance(row, dict) else {
        "strategy_key": row[0],
        "direction": row[1],
        "active_bars": row[2],
        "mfe_pct": row[3],
        "cooldown_remaining": row[4],
        "blocked_reentry_direction": row[5],
        "reentry_count": row[6],
        "last_action_at": row[7],
    }
    if str(values["strategy_key"]) != enrollment.strategy_key:
        raise ValueError("normalized manager LIVE state strategy_key mismatch")
    return NormalizedManagerLiveStateV1(
        pilot_key=enrollment.pilot_key,
        strategy_key=enrollment.strategy_key,
        direction=str(values["direction"]),
        active_bars=int(values["active_bars"]),
        mfe_pct=float(values["mfe_pct"]),
        cooldown_remaining=int(values["cooldown_remaining"]),
        blocked_reentry_direction=(
            None if values["blocked_reentry_direction"] is None else str(values["blocked_reentry_direction"])
        ),
        reentry_count=int(values["reentry_count"]),
        last_action_at=None if values["last_action_at"] is None else _utc(values["last_action_at"]),
    )


def _persist_manager_state_v1(state: NormalizedManagerLiveStateV1) -> None:
    if state.direction not in {DIRECTION_FLAT, DIRECTION_LONG, DIRECTION_SHORT}:
        raise ValueError("invalid normalized manager direction")
    if state.blocked_reentry_direction not in {None, DIRECTION_LONG, DIRECTION_SHORT}:
        raise ValueError("invalid normalized manager blocked re-entry direction")
    with connect() as db:
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_macd_norm_manager_state(
                pilot_key, strategy_key, direction, active_bars, mfe_pct,
                cooldown_remaining, blocked_reentry_direction, reentry_count,
                last_action_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, now())
            ON CONFLICT (pilot_key) DO UPDATE SET
                strategy_key=EXCLUDED.strategy_key,
                direction=EXCLUDED.direction,
                active_bars=EXCLUDED.active_bars,
                mfe_pct=EXCLUDED.mfe_pct,
                cooldown_remaining=EXCLUDED.cooldown_remaining,
                blocked_reentry_direction=EXCLUDED.blocked_reentry_direction,
                reentry_count=EXCLUDED.reentry_count,
                last_action_at=EXCLUDED.last_action_at,
                updated_at=now()
            """,
            (
                state.pilot_key,
                state.strategy_key,
                state.direction,
                int(state.active_bars),
                float(state.mfe_pct),
                int(state.cooldown_remaining),
                state.blocked_reentry_direction,
                int(state.reentry_count),
                state.last_action_at,
            ),
        )


def _manager_state_from_observation_v1(
    enrollment: StrategyEnrollmentV2,
    *,
    observed: PositionObservationV2 | None,
    observed_direction: str,
    action_at: datetime,
) -> NormalizedManagerLiveStateV1:
    mfe = 0.0
    if observed is not None and observed_direction in {DIRECTION_LONG, DIRECTION_SHORT}:
        mfe = max(0.0, float(observed.pnl_pct) / 100.0)
    return NormalizedManagerLiveStateV1(
        pilot_key=enrollment.pilot_key,
        strategy_key=enrollment.strategy_key,
        direction=observed_direction,
        active_bars=0,
        mfe_pct=mfe,
        cooldown_remaining=0,
        blocked_reentry_direction=None,
        reentry_count=0,
        last_action_at=action_at,
    )


def _manager_step_v1(
    state: NormalizedManagerLiveStateV1,
    *,
    raw_targets: tuple[str, ...],
    current_pnl_pct: float,
    rolling_vol: float,
    action_at: datetime,
    authoritative_cross: str | None = None,
) -> tuple[NormalizedManagerLiveStateV1, str]:
    """Advance the manager by one new closed 1m bar using actual-position P/L."""
    cfg = DEFAULT_POSITION_MANAGER_CONFIG_V1
    raw = raw_targets[-1] if raw_targets else DIRECTION_FLAT
    cooldown = max(0, int(state.cooldown_remaining) - 1)
    cross = (
        authoritative_cross
        if authoritative_cross in {DIRECTION_LONG, DIRECTION_SHORT}
        else None
    )

    if cross is not None:
        # A confirmed closed 5m MACD cross is already a lagging confirmation.
        # Management may protect profit between crosses but cannot delay/veto it.
        return replace(
            state,
            direction=cross,
            active_bars=0,
            mfe_pct=0.0,
            cooldown_remaining=0,
            blocked_reentry_direction=None,
            reentry_count=0,
            last_action_at=action_at,
        ), "authoritative_cross"

    if state.direction == DIRECTION_FLAT:
        if raw not in {DIRECTION_LONG, DIRECTION_SHORT}:
            return replace(
                state,
                cooldown_remaining=cooldown,
                reentry_count=0,
                last_action_at=action_at,
            ), "hold_flat"

        if state.blocked_reentry_direction == raw:
            reentry_count = int(state.reentry_count) + 1 if cooldown <= 0 else 0
            if cooldown <= 0 and reentry_count >= int(cfg.reentry_confirm_bars):
                return replace(
                    state,
                    direction=raw,
                    active_bars=0,
                    mfe_pct=0.0,
                    cooldown_remaining=0,
                    blocked_reentry_direction=None,
                    reentry_count=0,
                    last_action_at=action_at,
                ), "reentry"
            return replace(
                state,
                cooldown_remaining=cooldown,
                reentry_count=reentry_count,
                last_action_at=action_at,
            ), "reentry_wait"

        return replace(
            state,
            direction=raw,
            active_bars=0,
            mfe_pct=0.0,
            cooldown_remaining=0,
            blocked_reentry_direction=None,
            reentry_count=0,
            last_action_at=action_at,
        ), "entry"

    active_bars = int(state.active_bars) + 1
    mfe = max(float(state.mfe_pct), float(current_pnl_pct))
    arm = max(
        float(cfg.min_arm_pct),
        float(cfg.arm_vol_multiple) * max(0.0, float(rolling_vol)),
    )
    profit_lock_armed = active_bars >= int(cfg.min_hold_bars) and mfe >= arm and mfe > 0.0
    giveback_triggered = (
        profit_lock_armed
        and float(current_pnl_pct) <= mfe * (1.0 - float(cfg.max_giveback_fraction))
    )

    opposite = DIRECTION_SHORT if state.direction == DIRECTION_LONG else DIRECTION_LONG
    lookback = max(1, int(cfg.reversal_confirm_bars))
    confirmed_reversal = (
        len(raw_targets) >= lookback
        and all(item == opposite for item in raw_targets[-lookback:])
    )

    if giveback_triggered:
        return replace(
            state,
            direction=DIRECTION_FLAT,
            active_bars=0,
            mfe_pct=0.0,
            cooldown_remaining=int(cfg.reentry_cooldown_bars),
            blocked_reentry_direction=state.direction,
            reentry_count=0,
            last_action_at=action_at,
        ), "profit_lock"

    if confirmed_reversal:
        return replace(
            state,
            direction=opposite,
            active_bars=0,
            mfe_pct=0.0,
            cooldown_remaining=0,
            blocked_reentry_direction=None,
            reentry_count=0,
            last_action_at=action_at,
        ), "confirmed_reversal"

    return replace(
        state,
        active_bars=active_bars,
        mfe_pct=mfe,
        cooldown_remaining=cooldown,
        last_action_at=action_at,
    ), "hold"


def _latest_normalized_frame_v1(
    bars: tuple[CanonicalMarketBarV2, ...],
) -> tuple[pd.DataFrame, datetime, bool]:
    if len(bars) <= SUPERVISOR_WARMUP_1M_ROWS_V1:
        raise ValueError(
            f"normalized MACD LIVE needs >{SUPERVISOR_WARMUP_1M_ROWS_V1} closed canonical 1m bars"
        )
    frame, _, _ = replay_normalized_macd_supervisor_v1(bars)
    if frame.empty:
        raise ValueError("normalized MACD LIVE replay produced no rows")
    action_at = _utc(frame.index[-1].to_pydatetime())
    data_gap = False
    if len(bars) >= 2:
        gap = (_bar_action_at(bars[-1]) - _bar_action_at(bars[-2])).total_seconds() / 60.0
        data_gap = gap > MAX_LIVE_GAP_MINUTES_V1
    return frame, action_at, data_gap


def _clock_v1(action_at: datetime, frame: pd.DataFrame, *, data_gap: bool) -> Macd1mClockV2:
    current_score = float(frame["SCORE"].iloc[-1]) if "SCORE" in frame.columns else 0.0
    previous_score = (
        float(frame["SCORE"].iloc[-2])
        if len(frame) >= 2 and "SCORE" in frame.columns
        else current_score
    )
    return Macd1mClockV2(
        action_at=action_at,
        previous_macd=previous_score,
        previous_signal=0.0,
        previous_spread=previous_score,
        current_macd=current_score,
        current_signal=0.0,
        current_spread=current_score,
        cross_direction=None,
        data_gap=bool(data_gap),
    )


def run_macd_normalized_live_once_v1(
    enrollment: StrategyEnrollmentV2,
    *,
    db_path: str = "pricegauger.db",
    now: datetime | None = None,
    observations: tuple[PositionObservationV2, ...] | None = None,
) -> FastLiveCycleV2:
    """Run normalized MACD options through the common durable execution lifecycle.

    This strategy runtime never posts to Saxo. It creates only the same durable
    intent/request state used by the other AutoManager strategies. CLOSE -> confirmed
    FLAT -> OPEN, sizing, precheck and broker submission remain downstream authority.
    """
    if enrollment.execution_mode != EXECUTION_MODE_LIVE or not enrollment.enabled:
        raise ValueError("normalized MACD runtime only executes active LIVE_MANAGE enrollments")
    if enrollment.strategy_key not in MACD_NORMALIZED_LIVE_STRATEGIES_V1:
        raise ValueError("normalized MACD runtime received an unsupported strategy")

    ensure_macd_normalized_live_schema_v1()
    end = _utc(now or datetime.now(timezone.utc))
    loaded = CanonicalMarketBarStoreV2(db_path).load_instrument_range(
        instrument_id=int(enrollment.instrument_id),
        start=end - MACD_WARMUP_LOOKBACK_V1,
        end=end,
        limit=MACD_WARMUP_MAX_BARS_V1,
    )
    eligible = tuple(
        sorted(
            (item for item in loaded if _bar_action_at(item) <= end),
            key=lambda item: _utc(item.bar_time),
        )
    )
    if len(eligible) <= SUPERVISOR_WARMUP_1M_ROWS_V1:
        raise ValueError("normalized MACD LIVE has insufficient closed canonical 1m history")
    action_at = _bar_action_at(eligible[-1])

    if observations is None:
        client = configured_client()
        if client is None:
            raise RuntimeError("Saxo client is not configured")
        observations = _position_observations_v2(client)
    observed = _exact_product_observation(enrollment, observations)
    observed_direction = _observed_direction(observed)

    state = load_fast_live_state_v2(enrollment)
    manager_state = (
        _load_manager_state_v1(enrollment)
        if enrollment.strategy_key == MACD_NORM_MANAGER_STRATEGY_V1
        else None
    )

    if state is None:
        state = FastLiveStateV2(
            pilot_key=enrollment.pilot_key,
            strategy_key=enrollment.strategy_key,
            desired_direction=observed_direction,
            last_action_at=action_at,
        )
        _persist_state_v2(state)
        _persist_bootstrap_v2(enrollment, state, observed)
        if enrollment.strategy_key == MACD_NORM_MANAGER_STRATEGY_V1:
            manager_state = _manager_state_from_observation_v1(
                enrollment,
                observed=observed,
                observed_direction=observed_direction,
                action_at=action_at,
            )
            _persist_manager_state_v1(manager_state)
        return FastLiveCycleV2(
            enrollment.pilot_key,
            enrollment.strategy_key,
            observed_direction,
            observed_direction,
            None,
            action_at,
            False,
            False,
            True,
            "BOOTSTRAP_MACD_NORM",
        )

    externally_resynced = False
    if state.pending_target_direction is not None and observed_direction == state.pending_target_direction:
        state = _clear_intent_v2(state, observed_direction=observed_direction)
        _persist_state_v2(state)
    elif state.pending_target_direction is None and observed_direction != state.desired_direction:
        state = _clear_intent_v2(state, observed_direction=observed_direction)
        _persist_state_v2(state)
        externally_resynced = True

    if enrollment.strategy_key == MACD_NORM_MANAGER_STRATEGY_V1:
        if manager_state is None or externally_resynced:
            manager_state = _manager_state_from_observation_v1(
                enrollment,
                observed=observed,
                observed_direction=observed_direction,
                action_at=action_at,
            )
            _persist_manager_state_v1(manager_state)

    if state.pending_target_direction is not None and observed_direction != state.pending_target_direction:
        equity = load_pilot_equity_v2(pilot_key=enrollment.pilot_key)
        continued = _persist_intent_and_request_v2(
            enrollment=enrollment,
            state=state,
            observed=observed,
            observed_direction=observed_direction,
            budget_amount=equity.entry_budget,
            budget_currency=equity.currency,
            supersede_prior=False,
        )
        _persist_state_v2(state)
        return FastLiveCycleV2(
            enrollment.pilot_key,
            enrollment.strategy_key,
            state.desired_direction,
            observed_direction,
            state.pending_target_direction,
            action_at,
            False,
            bool(continued),
            False,
            "PENDING_TRANSITION_RETRY_READY" if continued else "PENDING_TRANSITION_CONTINUED",
        )

    if state.last_action_at is not None and action_at <= state.last_action_at:
        return FastLiveCycleV2(
            enrollment.pilot_key,
            enrollment.strategy_key,
            state.desired_direction,
            observed_direction,
            state.pending_target_direction,
            action_at,
            False,
            False,
            False,
            "NO_NEW_MACD_NORM_ACTION",
        )

    frame, replay_action_at, data_gap = _latest_normalized_frame_v1(eligible)
    action_at = replay_action_at
    clock = _clock_v1(action_at, frame, data_gap=data_gap)
    fresh = timedelta(0) <= (end - action_at) <= FRESH_MAX_AGE
    if not fresh or data_gap:
        state = replace(state, last_action_at=action_at)
        _persist_state_v2(state)
        if manager_state is not None:
            manager_state = replace(manager_state, last_action_at=action_at)
            _persist_manager_state_v1(manager_state)
        return FastLiveCycleV2(
            enrollment.pilot_key,
            enrollment.strategy_key,
            state.desired_direction,
            observed_direction,
            None,
            action_at,
            True,
            False,
            False,
            "STALE_MACD_NORM_ACTION_SKIPPED" if not fresh else "MACD_NORM_DATA_GAP_SKIPPED",
        )

    raw_directions = tuple(_direction_from_target(item) for item in frame["TARGET"].tail(8))
    raw_candidate = raw_directions[-1]
    authoritative_cross = (
        _direction_from_target(float(frame["AUTHORITATIVE_CROSS"].iloc[-1]))
        if "AUTHORITATIVE_CROSS" in frame.columns
        and int(frame["AUTHORITATIVE_CROSS"].iloc[-1]) in (-1, 1)
        else None
    )
    score = float(frame["SCORE"].iloc[-1])
    confidence = float(frame["CONFIDENCE"].iloc[-1])

    manager_reason = ""
    if enrollment.strategy_key == MACD_NORM_MANAGER_STRATEGY_V1:
        assert manager_state is not None
        current_pnl = (
            float(observed.pnl_pct) / 100.0
            if observed is not None
            and observed_direction == manager_state.direction
            and manager_state.direction in {DIRECTION_LONG, DIRECTION_SHORT}
            else 0.0
        )
        prices = frame["PRICE"].astype("float64")
        cfg = DEFAULT_POSITION_MANAGER_CONFIG_V1
        rolling_vol = float(
            prices.pct_change()
            .rolling(
                int(cfg.volatility_lookback),
                min_periods=min(10, int(cfg.volatility_lookback)),
            )
            .std()
            .fillna(0.0)
            .iloc[-1]
        )
        manager_state, manager_reason = _manager_step_v1(
            manager_state,
            raw_targets=raw_directions,
            current_pnl_pct=current_pnl,
            rolling_vol=rolling_vol,
            action_at=action_at,
            authoritative_cross=authoritative_cross,
        )
        _persist_manager_state_v1(manager_state)
        candidate = manager_state.direction
    else:
        candidate = raw_candidate

    request_created = False
    reason = "TARGET_UNCHANGED"
    if candidate != state.desired_direction:
        signal = (
            f"MACD_NORM:{candidate}:raw={raw_candidate}:score={score:+.3f}:"
            f"confidence={confidence:.3f}"
        )
        if authoritative_cross is not None:
            signal += f":authoritative_cross={authoritative_cross}"
        if manager_reason:
            signal += f":manager={manager_reason}"
        state = _new_intent_state_v2(
            state,
            target=candidate,
            observed_direction=observed_direction,
            clock=clock,
            signal=signal,
        )
        equity = load_pilot_equity_v2(pilot_key=enrollment.pilot_key)
        request_created = _persist_intent_and_request_v2(
            enrollment=enrollment,
            state=state,
            observed=observed,
            observed_direction=observed_direction,
            budget_amount=equity.entry_budget,
            budget_currency=equity.currency,
            supersede_prior=True,
        )
        reason = f"TARGET_{candidate}" + (f"_{manager_reason.upper()}" if manager_reason else "")
    else:
        state = replace(state, last_action_at=action_at)

    _persist_state_v2(state)
    return FastLiveCycleV2(
        enrollment.pilot_key,
        enrollment.strategy_key,
        state.desired_direction,
        observed_direction,
        state.pending_target_direction,
        action_at,
        True,
        bool(request_created),
        False,
        reason,
    )


__all__ = [
    "MACD_NORMALIZED_LIVE_STRATEGIES_V1",
    "MAX_LIVE_GAP_MINUTES_V1",
    "NormalizedManagerLiveStateV1",
    "_manager_step_v1",
    "ensure_macd_normalized_live_schema_v1",
    "run_macd_normalized_live_once_v1",
]
