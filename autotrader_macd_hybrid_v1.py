from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from typing import Any

from autotrader_fast_live_runtime_v2 import (
    FRESH_MAX_AGE,
    HISTORY_MINUTES,
    FastLiveCycleV2,
    FastLiveStateV2,
    _clear_intent_v2,
    _exact_product_observation,
    _macd_1m_clock_v2,
    _new_intent_state_v2,
    _observed_direction,
    _persist_bootstrap_v2,
    _persist_intent_and_request_v2,
    _persist_state_v2,
    ensure_fast_live_schema_v2,
    load_fast_live_state_v2,
)
from autotrader_macd_timeframe_controls_v1 import _crosses_by_action_v1
from autotrader_mtf_entry_shadow_v2 import closed_bars_v2, macd_observations_v2
from autotrader_pilot_equity_v2 import load_pilot_equity_v2
from autotrader_risk_control_v2 import PositionObservationV2, _position_observations_v2
from autotrader_shadow_benchmark_v2 import (
    BENCHMARK_MAX_1M_BARS,
    BENCHMARK_WARMUP_DAYS,
    STATE_FLAT,
    STATE_LONG,
    STATE_SHORT,
    ShadowBenchmarkSeriesV2,
    ShadowEquityPointV2,
    apply_shadow_return_v2,
)
from autotrader_strategy_enrollment_v2 import EXECUTION_MODE_LIVE, StrategyEnrollmentV2
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2, CanonicalMarketBarV2
from saxo_provider import configured_client


HYBRID_ENTRY_TIMEFRAMES_MINUTES_V1 = (2, 5)
HYBRID_STRATEGY_KEYS_V1 = {
    2: "macd-hybrid-exit-1m-entry-2m-v1",
    5: "macd-hybrid-exit-1m-entry-5m-v1",
}
HYBRID_SERIES_VERSION_V1 = "MACD-HYBRID-EXIT1M-ENTRYTF-12-26-9-v2"
DIRECTIONS = {STATE_FLAT, STATE_LONG, STATE_SHORT}


def _utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _action_at(bar: CanonicalMarketBarV2) -> datetime:
    return _utc(bar.bar_time).replace(second=0, microsecond=0) + timedelta(minutes=1)


def _regime_from_spread_v1(spread: float) -> str:
    value = float(spread)
    if value > 0.0:
        return STATE_LONG
    if value < 0.0:
        return STATE_SHORT
    return STATE_FLAT


def _entry_regime_updates_v1(
    bars: tuple[CanonicalMarketBarV2, ...],
    *,
    timeframe_minutes: int,
) -> dict[datetime, str]:
    """Return only trustworthy closed-timeframe MACD regime updates.

    A regime update is emitted only when the latest two closed timeframe bars are
    contiguous, matching the same no-invented-signal rule used by the cross detector.
    The value can then be carried forward on the canonical 1m decision clock.
    """
    minutes = int(timeframe_minutes)
    if not bars:
        return {}
    closed = closed_bars_v2(
        tuple(item.point for item in bars),
        market=str(bars[0].market_name),
        timeframe_minutes=minutes,
    )
    observations = macd_observations_v2(closed, timeframe_minutes=minutes)
    expected = timedelta(minutes=minutes)
    updates: dict[datetime, str] = {}
    for previous, current in zip(observations, observations[1:]):
        if current.closed_at - previous.closed_at != expected:
            continue
        updates[_utc(current.closed_at)] = _regime_from_spread_v1(current.spread)
    return updates


def _entry_regime_at_v1(updates: dict[datetime, str], action_at: datetime) -> str:
    regime = STATE_FLAT
    action = _utc(action_at)
    for observed_at in sorted(updates):
        if observed_at > action:
            break
        regime = updates[observed_at]
    return regime


def hybrid_strategy_key_v1(entry_timeframe_minutes: int) -> str:
    minutes = int(entry_timeframe_minutes)
    try:
        return HYBRID_STRATEGY_KEYS_V1[minutes]
    except KeyError as exc:
        raise ValueError(f"unsupported hybrid entry timeframe: {minutes}m") from exc


def hybrid_strategy_label_v1(entry_timeframe_minutes: int) -> str:
    minutes = int(entry_timeframe_minutes)
    if minutes not in HYBRID_STRATEGY_KEYS_V1:
        raise ValueError(f"unsupported hybrid entry timeframe: {minutes}m")
    return f"MACD hybrid · exit 1m / entry {minutes}m"


def hybrid_entry_timeframe_for_strategy_v1(strategy_key: str) -> int:
    key = str(strategy_key)
    for minutes, candidate in HYBRID_STRATEGY_KEYS_V1.items():
        if candidate == key:
            return int(minutes)
    raise ValueError(f"unsupported hybrid strategy: {key}")


def hybrid_target_v1(
    current_state: str,
    *,
    cross_1m: str | None,
    cross_entry: str | None,
    entry_regime: str | None = None,
    data_gap: bool,
) -> str:
    """Asymmetric MACD policy: fast de-risking, slower confirmation for re-risking.

    LONG/SHORT positions can go FLAT on an opposite 1m cross. From FLAT, a fresh
    entry-timeframe cross still enters directly. In addition, a fresh 1m recovery
    cross may re-enter when the latest trustworthy closed entry-timeframe MACD regime
    already agrees with that direction. This avoids stranding the strategy FLAT after
    a fast protective exit merely because the slower MACD never crossed through zero
    in the meantime.

    Any actual reversal still flows through the shared CLOSE -> confirmed FLAT -> OPEN
    execution lifecycle; this function only selects the desired strategic target.
    """
    state = str(current_state).upper()
    if state not in DIRECTIONS:
        raise ValueError(f"unsupported hybrid state: {current_state}")
    if data_gap:
        return state

    entry = None if cross_entry is None else str(cross_entry).upper()
    fast = None if cross_1m is None else str(cross_1m).upper()
    regime = STATE_FLAT if entry_regime is None else str(entry_regime).upper()
    if entry not in DIRECTIONS - {STATE_FLAT} and entry is not None:
        raise ValueError(f"unsupported entry cross: {cross_entry}")
    if fast not in DIRECTIONS - {STATE_FLAT} and fast is not None:
        raise ValueError(f"unsupported 1m cross: {cross_1m}")
    if regime not in DIRECTIONS:
        raise ValueError(f"unsupported entry regime: {entry_regime}")

    if state == STATE_FLAT:
        if entry in {STATE_LONG, STATE_SHORT}:
            return entry
        if fast in {STATE_LONG, STATE_SHORT} and regime == fast:
            return fast
        return STATE_FLAT

    if state == STATE_LONG:
        if entry == STATE_SHORT:
            return STATE_SHORT
        if fast == STATE_SHORT:
            return STATE_FLAT
        return STATE_LONG

    if entry == STATE_LONG:
        return STATE_LONG
    if fast == STATE_LONG:
        return STATE_FLAT
    return STATE_SHORT


def _series_for_hybrid_v1(
    bars: tuple[CanonicalMarketBarV2, ...],
    *,
    entry_timeframe_minutes: int,
    seed_equity: float,
    currency: str,
    started_at: datetime,
    as_of: datetime,
) -> ShadowBenchmarkSeriesV2 | None:
    minutes = int(entry_timeframe_minutes)
    if minutes not in HYBRID_STRATEGY_KEYS_V1:
        raise ValueError(f"unsupported hybrid entry timeframe: {minutes}m")
    seed = float(seed_equity)
    if not math.isfinite(seed) or seed <= 0:
        raise ValueError("seed_equity must be finite and positive")
    started = _utc(started_at)
    end = _utc(as_of)
    if end < started:
        raise ValueError("comparison end precedes start")

    price_clock = tuple(item for item in bars if started <= _action_at(item) <= end)
    if not price_clock:
        return None

    crosses_1m = _crosses_by_action_v1(bars, timeframe_minutes=1)
    crosses_entry = _crosses_by_action_v1(bars, timeframe_minutes=minutes)
    regime_updates = _entry_regime_updates_v1(bars, timeframe_minutes=minutes)
    state = STATE_FLAT
    equity = seed
    prior_price = float(price_clock[0].close)
    if prior_price <= 0:
        raise ValueError("hybrid MACD control price must be positive")
    first_at = _action_at(price_clock[0])
    entry_regime = _entry_regime_at_v1(regime_updates, first_at)
    points = [ShadowEquityPointV2(closed_at=first_at, equity=seed, position_state=state)]

    for item in price_clock[1:]:
        action_at = _action_at(item)
        if action_at in regime_updates:
            entry_regime = regime_updates[action_at]
        price = float(item.close)
        if price <= 0:
            raise ValueError("hybrid MACD control price must be positive")
        equity = apply_shadow_return_v2(
            equity=equity,
            position_state=state,
            price_return=(price / prior_price) - 1.0,
        )
        if equity <= 0:
            state = STATE_FLAT
        else:
            state = hybrid_target_v1(
                state,
                cross_1m=crosses_1m.get(action_at),
                cross_entry=crosses_entry.get(action_at),
                entry_regime=entry_regime,
                data_gap=False,
            )
        points.append(
            ShadowEquityPointV2(
                closed_at=action_at,
                equity=float(equity),
                position_state=state,
            )
        )
        prior_price = price

    return ShadowBenchmarkSeriesV2(
        strategy_key=hybrid_strategy_key_v1(minutes),
        execution_mode="SHADOW_ADAPTIVE",
        currency=str(currency),
        seed_equity=seed,
        started_at=first_at,
        points=tuple(points),
    )


def load_macd_hybrid_series_v1(
    *,
    instrument_id: int,
    seed_equity: float,
    currency: str,
    started_at: datetime,
    as_of: datetime,
    db_path: str = "pricegauger.db",
) -> tuple[ShadowBenchmarkSeriesV2, ...]:
    started = _utc(started_at)
    end = _utc(as_of)
    bars = CanonicalMarketBarStoreV2(db_path).load_instrument_range(
        instrument_id=int(instrument_id),
        start=started - timedelta(days=BENCHMARK_WARMUP_DAYS),
        end=end,
        limit=BENCHMARK_MAX_1M_BARS,
    )
    if not bars:
        return ()
    materialized = tuple(bars)
    result = []
    for minutes in HYBRID_ENTRY_TIMEFRAMES_MINUTES_V1:
        series = _series_for_hybrid_v1(
            materialized,
            entry_timeframe_minutes=minutes,
            seed_equity=float(seed_equity),
            currency=str(currency),
            started_at=started,
            as_of=end,
        )
        if series is not None:
            result.append(series)
    return tuple(result)


def _hybrid_signal_name_v1(
    *,
    target: str,
    cross_1m: str | None,
    cross_entry: str | None,
    entry_regime: str,
    minutes: int,
) -> str:
    if cross_entry == STATE_LONG and target == STATE_LONG:
        return f"ENTRY_{minutes}M_CROSS_UP"
    if cross_entry == STATE_SHORT and target == STATE_SHORT:
        return f"ENTRY_{minutes}M_CROSS_DOWN"
    if cross_1m == STATE_LONG and entry_regime == STATE_LONG and target == STATE_LONG:
        return f"REENTRY_{minutes}M_BULL_REGIME_1M_CROSS_UP"
    if cross_1m == STATE_SHORT and entry_regime == STATE_SHORT and target == STATE_SHORT:
        return f"REENTRY_{minutes}M_BEAR_REGIME_1M_CROSS_DOWN"
    if cross_1m == STATE_LONG and target == STATE_FLAT:
        return "EXIT_1M_CROSS_UP"
    if cross_1m == STATE_SHORT and target == STATE_FLAT:
        return "EXIT_1M_CROSS_DOWN"
    if target == STATE_LONG:
        return f"ENTRY_{minutes}M_LONG"
    if target == STATE_SHORT:
        return f"ENTRY_{minutes}M_SHORT"
    return "EXIT_1M_FLAT"


def run_macd_hybrid_live_once_v1(
    enrollment: StrategyEnrollmentV2,
    *,
    db_path: str = "pricegauger.db",
    now: datetime | None = None,
    observations: tuple[PositionObservationV2, ...] | None = None,
) -> FastLiveCycleV2:
    if enrollment.execution_mode != EXECUTION_MODE_LIVE or not enrollment.enabled:
        raise ValueError("hybrid runtime only executes active LIVE_MANAGE enrollments")
    minutes = hybrid_entry_timeframe_for_strategy_v1(enrollment.strategy_key)
    ensure_fast_live_schema_v2()

    end = _utc(now or datetime.now(timezone.utc))
    bars = CanonicalMarketBarStoreV2(db_path).load_instrument_range(
        instrument_id=int(enrollment.instrument_id),
        start=end - timedelta(minutes=HISTORY_MINUTES),
        end=end,
        limit=2_000,
    )
    if not bars:
        raise ValueError("hybrid LIVE has no exact canonical 1m history")
    materialized = tuple(bars)
    clock = _macd_1m_clock_v2(materialized, now=end)
    entry_cross = _crosses_by_action_v1(materialized, timeframe_minutes=minutes).get(clock.action_at)
    regime_updates = _entry_regime_updates_v1(materialized, timeframe_minutes=minutes)
    entry_regime = _entry_regime_at_v1(regime_updates, clock.action_at)

    if observations is None:
        client = configured_client()
        if client is None:
            raise RuntimeError("Saxo client is not configured")
        observations = _position_observations_v2(client)
    observed = _exact_product_observation(enrollment, observations)
    observed_direction = _observed_direction(observed)

    state = load_fast_live_state_v2(enrollment)
    if state is None:
        state = FastLiveStateV2(
            pilot_key=enrollment.pilot_key,
            strategy_key=enrollment.strategy_key,
            desired_direction=observed_direction,
            last_action_at=clock.action_at,
        )
        _persist_state_v2(state)
        _persist_bootstrap_v2(enrollment, state, observed)
        return FastLiveCycleV2(
            enrollment.pilot_key,
            enrollment.strategy_key,
            state.desired_direction,
            observed_direction,
            None,
            clock.action_at,
            False,
            False,
            True,
            "BOOTSTRAP_NO_REPLAY",
        )

    if state.pending_target_direction is not None:
        if observed_direction == state.pending_target_direction:
            state = _clear_intent_v2(state, observed_direction=observed_direction)
            _persist_state_v2(state)
    elif observed_direction != state.desired_direction:
        state = _clear_intent_v2(state, observed_direction=observed_direction)
        _persist_state_v2(state)

    new_action = state.last_action_at is None or clock.action_at > state.last_action_at
    request_created = False
    reason = "NO_NEW_1M_ACTION"

    if new_action:
        fresh = timedelta(0) <= (end - clock.action_at) <= FRESH_MAX_AGE
        if not fresh:
            state = FastLiveStateV2(
                pilot_key=state.pilot_key,
                strategy_key=state.strategy_key,
                desired_direction=state.desired_direction,
                last_action_at=clock.action_at,
                pending_target_direction=state.pending_target_direction,
                intent_event_id=state.intent_event_id,
                intent_signal_at=state.intent_signal_at,
                intent_signal=state.intent_signal,
                intent_previous_macd=state.intent_previous_macd,
                intent_previous_signal=state.intent_previous_signal,
                intent_current_macd=state.intent_current_macd,
                intent_current_signal=state.intent_current_signal,
            )
            _persist_state_v2(state)
            reason = "STALE_1M_ACTION_SKIPPED"
        else:
            target = hybrid_target_v1(
                state.desired_direction,
                cross_1m=clock.cross_direction,
                cross_entry=entry_cross,
                entry_regime=entry_regime,
                data_gap=clock.data_gap,
            )
            if target != state.desired_direction:
                signal = _hybrid_signal_name_v1(
                    target=target,
                    cross_1m=clock.cross_direction,
                    cross_entry=entry_cross,
                    entry_regime=entry_regime,
                    minutes=minutes,
                )
                state = _new_intent_state_v2(
                    state,
                    target=target,
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
                reason = f"TARGET_{target}"
            else:
                state = FastLiveStateV2(
                    pilot_key=state.pilot_key,
                    strategy_key=state.strategy_key,
                    desired_direction=state.desired_direction,
                    last_action_at=clock.action_at,
                    pending_target_direction=state.pending_target_direction,
                    intent_event_id=state.intent_event_id,
                    intent_signal_at=state.intent_signal_at,
                    intent_signal=state.intent_signal,
                    intent_previous_macd=state.intent_previous_macd,
                    intent_previous_signal=state.intent_previous_signal,
                    intent_current_macd=state.intent_current_macd,
                    intent_current_signal=state.intent_current_signal,
                )
                _persist_state_v2(state)
                reason = "TARGET_UNCHANGED"

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
        request_created = request_created or continued
        if not new_action:
            reason = "PENDING_TRANSITION_CONTINUED"

    _persist_state_v2(state)
    return FastLiveCycleV2(
        pilot_key=enrollment.pilot_key,
        strategy_key=enrollment.strategy_key,
        desired_direction=state.desired_direction,
        observed_direction=observed_direction,
        pending_target_direction=state.pending_target_direction,
        action_at=clock.action_at,
        processed=new_action,
        request_created=request_created,
        bootstrap=False,
        reason=reason,
    )


__all__ = [
    "HYBRID_ENTRY_TIMEFRAMES_MINUTES_V1",
    "HYBRID_SERIES_VERSION_V1",
    "HYBRID_STRATEGY_KEYS_V1",
    "hybrid_entry_timeframe_for_strategy_v1",
    "hybrid_strategy_key_v1",
    "hybrid_strategy_label_v1",
    "hybrid_target_v1",
    "load_macd_hybrid_series_v1",
    "run_macd_hybrid_live_once_v1",
]
