from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from autotrader_fast_live_runtime_v2 import (
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
    _persist_state_v2,
    ensure_fast_live_schema_v2,
    load_fast_live_state_v2,
)
from autotrader_macd_binary_execution_v1 import ensure_binary_macd_max_sizing_v1
from autotrader_macd_intrabar_clock_v1 import ensure_macd_intrabar_probe_schema_v1, live_macd_intrabar_clock_v1
from autotrader_macd_models_v1 import (
    LONG,
    SHORT,
    adaptive_timeframe_v1,
    macd2_10_target_v1,
    macd2_stochastic_target_v1,
    stochastic_direction_score_v1,
)
from autotrader_macd_timeframe_live_v1 import (
    MACD_WARMUP_LOOKBACK_V1,
    MACD_WARMUP_MAX_BARS_V1,
    _persist_binary_macd_intent_v1,
)
from autotrader_mtf_entry_shadow_v2 import closed_bars_v2, macd_observations_v2
from autotrader_pilot_equity_v2 import load_pilot_equity_v2
from autotrader_risk_control_v2 import PositionObservationV2, _position_observations_v2
from autotrader_strategy_enrollment_v2 import EXECUTION_MODE_LIVE, StrategyEnrollmentV2
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2, CanonicalMarketBarV2
from saxo_provider import configured_client
from trading_desk_indicators import calculate_indicators


MACD2_10_STRATEGY_V1 = "macd2-10-v1"
MACD2_S_STRATEGY_V1 = "macd2-s-v1"
MACD_A_STRATEGY_V1 = "macd-a-v1"
MACD_MODEL_LIVE_STRATEGIES_V1 = {
    MACD2_10_STRATEGY_V1,
    MACD2_S_STRATEGY_V1,
    MACD_A_STRATEGY_V1,
}


def _utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _closed_observations_v1(
    bars: tuple[CanonicalMarketBarV2, ...],
    *,
    market_name: str,
    timeframe_minutes: int,
):
    closed = closed_bars_v2(
        tuple(item.point for item in bars),
        market=market_name,
        timeframe_minutes=int(timeframe_minutes),
    )
    observations = macd_observations_v2(closed, timeframe_minutes=int(timeframe_minutes))
    if len(observations) < 2:
        raise ValueError(f"MACD model needs enough {timeframe_minutes}m history")
    return closed, observations


def _clock_from_closed_v1(observations) -> Macd1mClockV2:
    previous, current = observations[-2], observations[-1]
    target = DIRECTION_LONG if current.spread > 0.0 else DIRECTION_SHORT if current.spread < 0.0 else None
    return Macd1mClockV2(
        action_at=_utc(current.closed_at),
        previous_macd=float(previous.macd),
        previous_signal=float(previous.signal),
        previous_spread=float(previous.spread),
        current_macd=float(current.macd),
        current_signal=float(current.signal),
        current_spread=float(current.spread),
        cross_direction=target,
        data_gap=False,
    )


def _stochastic_score_v1(bars: tuple[CanonicalMarketBarV2, ...], *, market_name: str) -> float:
    closed, _ = _closed_observations_v1(bars, market_name=market_name, timeframe_minutes=1)
    indicators = calculate_indicators(closed)
    if len(indicators.stochastic_k) < 2 or len(indicators.stochastic_d) < 2:
        return 0.0
    k_by_time = {str(item.bar_time): float(item.value) for item in indicators.stochastic_k}
    d_by_time = {str(item.bar_time): float(item.value) for item in indicators.stochastic_d}
    common = [str(item.bar_time) for item in closed if str(item.bar_time) in k_by_time and str(item.bar_time) in d_by_time]
    if len(common) < 2:
        return 0.0
    previous_at, current_at = common[-2], common[-1]
    return stochastic_direction_score_v1(
        previous_k=k_by_time[previous_at],
        previous_d=d_by_time[previous_at],
        current_k=k_by_time[current_at],
        current_d=d_by_time[current_at],
    )


def _recent_micro_edge_v1(observations) -> tuple[float, float]:
    """Measure whether recent 1m MACD flips produced follow-through over 3 minutes."""
    if len(observations) < 12:
        return 0.5, 0.5
    outcomes: list[bool] = []
    for index in range(1, len(observations) - 3):
        previous = observations[index - 1]
        current = observations[index]
        direction = 0
        if previous.spread <= 0.0 < current.spread:
            direction = 1
        elif previous.spread >= 0.0 > current.spread:
            direction = -1
        if not direction:
            continue
        future = observations[index + 3]
        move = float(future.close) - float(current.close)
        outcomes.append((move * direction) > 0.0)
    recent = outcomes[-8:]
    if len(recent) < 3:
        return 0.5, 0.5
    edge = sum(1 for item in recent if item) / float(len(recent))
    return edge, 1.0 - edge


def _adaptive_clock_v1(bars: tuple[CanonicalMarketBarV2, ...], *, market_name: str) -> tuple[Macd1mClockV2, int, float, float]:
    _, one = _closed_observations_v1(bars, market_name=market_name, timeframe_minutes=1)
    micro_edge, noise = _recent_micro_edge_v1(one)
    minutes = adaptive_timeframe_v1(micro_edge=micro_edge, noise=noise)
    _, selected = _closed_observations_v1(bars, market_name=market_name, timeframe_minutes=minutes)
    return _clock_from_closed_v1(selected), minutes, micro_edge, noise


def _candidate_v1(
    enrollment: StrategyEnrollmentV2,
    bars: tuple[CanonicalMarketBarV2, ...],
    *,
    db_path: str,
    now: datetime,
    current: str,
) -> tuple[Macd1mClockV2, str, str]:
    if enrollment.strategy_key == MACD2_10_STRATEGY_V1:
        clock = live_macd_intrabar_clock_v1(
            enrollment,
            bars,
            timeframe_minutes=2,
            db_path=db_path,
            now=now,
        )
        _, slow = _closed_observations_v1(bars, market_name=enrollment.market_name, timeframe_minutes=10)
        target = macd2_10_target_v1(clock.current_spread, slow[-1].spread, current=current)
        return clock, target, f"2m={clock.current_spread:+.6f};10m={slow[-1].spread:+.6f}"

    if enrollment.strategy_key == MACD2_S_STRATEGY_V1:
        clock = live_macd_intrabar_clock_v1(
            enrollment,
            bars,
            timeframe_minutes=2,
            db_path=db_path,
            now=now,
        )
        stochastic = _stochastic_score_v1(bars, market_name=enrollment.market_name)
        target = macd2_stochastic_target_v1(
            spread_2m=clock.current_spread,
            stochastic_score=stochastic,
            current=current,
            stochastic_weight=0.20,
            execute_threshold=0.70,
        )
        return clock, target, f"2m={clock.current_spread:+.6f};stoch={stochastic:+.2f}"

    if enrollment.strategy_key == MACD_A_STRATEGY_V1:
        clock, minutes, micro_edge, noise = _adaptive_clock_v1(bars, market_name=enrollment.market_name)
        target = LONG if clock.current_spread > 0.0 else SHORT if clock.current_spread < 0.0 else current
        return clock, target, f"tf={minutes}m;edge={micro_edge:.2f};noise={noise:.2f}"

    raise ValueError(f"unsupported MACD model LIVE strategy: {enrollment.strategy_key}")


def run_macd_model_live_once_v1(
    enrollment: StrategyEnrollmentV2,
    *,
    db_path: str = "pricegauger.db",
    now: datetime | None = None,
    observations: tuple[PositionObservationV2, ...] | None = None,
) -> FastLiveCycleV2:
    """Run one compact experimental MACD model through the hardened executor."""
    if enrollment.execution_mode != EXECUTION_MODE_LIVE or not enrollment.enabled:
        raise ValueError("MACD model runtime only executes active LIVE_MANAGE enrollments")
    if enrollment.strategy_key not in MACD_MODEL_LIVE_STRATEGIES_V1:
        raise ValueError("MACD model runtime received an unsupported strategy")

    ensure_fast_live_schema_v2()
    ensure_macd_intrabar_probe_schema_v1()
    client = configured_client()
    if client is not None:
        ensure_binary_macd_max_sizing_v1(enrollment, client)

    end = _utc(now or datetime.now(timezone.utc))
    bars = CanonicalMarketBarStoreV2(db_path).load_instrument_range(
        instrument_id=int(enrollment.instrument_id),
        start=end - MACD_WARMUP_LOOKBACK_V1,
        end=end,
        limit=MACD_WARMUP_MAX_BARS_V1,
    )
    if not bars:
        raise ValueError("MACD model LIVE has no exact canonical 1m history")

    if observations is None:
        if client is None:
            raise RuntimeError("Saxo client is not configured")
        observations = _position_observations_v2(client)
    observed = _exact_product_observation(enrollment, observations)
    observed_direction = _observed_direction(observed)

    state = load_fast_live_state_v2(enrollment)
    current_target = observed_direction if state is None else state.desired_direction
    clock, candidate, evidence = _candidate_v1(
        enrollment,
        tuple(bars),
        db_path=db_path,
        now=end,
        current=current_target,
    )

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
            "BOOTSTRAP_MODEL",
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
    reason = "NO_NEW_MODEL_ACTION"

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
            reason = "STALE_MODEL_ACTION_SKIPPED"
        elif clock.data_gap:
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
            reason = "MODEL_PROBE_PRIMED"
        elif candidate in {LONG, SHORT} and candidate != state.desired_direction:
            signal = f"{enrollment.strategy_key}:{candidate}:{evidence}"
            state = _new_intent_state_v2(
                state,
                target=candidate,
                observed_direction=observed_direction,
                clock=clock,
                signal=signal,
            )
            equity = load_pilot_equity_v2(pilot_key=enrollment.pilot_key)
            request_created = _persist_binary_macd_intent_v1(
                enrollment=enrollment,
                state=state,
                observed=observed,
                observed_direction=observed_direction,
                budget_amount=equity.entry_budget,
                budget_currency=equity.currency,
                supersede_prior=True,
            )
            reason = f"TARGET_{candidate}"
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
        continued = _persist_binary_macd_intent_v1(
            enrollment=enrollment,
            state=state,
            observed=observed,
            observed_direction=observed_direction,
            budget_amount=equity.entry_budget,
            budget_currency=equity.currency,
            supersede_prior=False,
        )
        request_created = request_created or continued
        if continued:
            reason = "PENDING_TRANSITION_RETRY_READY"
        elif not new_action:
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
    "MACD2_10_STRATEGY_V1",
    "MACD2_S_STRATEGY_V1",
    "MACD_A_STRATEGY_V1",
    "MACD_MODEL_LIVE_STRATEGIES_V1",
    "run_macd_model_live_once_v1",
]
