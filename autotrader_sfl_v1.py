from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from typing import Any

import pandas as pd

from autotrader_fast_live_runtime_v2 import (
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


SFL_TIMEFRAMES_V1 = (1, 2, 5, 10)
SFL_STRATEGY_KEYS_V1 = {minutes: f"sfl-{minutes}m-v1" for minutes in SFL_TIMEFRAMES_V1}
SFL_SERIES_VERSION_V1 = "SFL-STATE-IMPULSE-12-26-9-v1"
DIRECTIONS = {STATE_FLAT, STATE_LONG, STATE_SHORT}
ENTER_THRESHOLD = 0.50
FAST_ENTER_THRESHOLD = 0.32
EXIT_THRESHOLD = 0.15
NOISE_FLAT_THRESHOLD = 0.68
IMPULSE_ALERT_THRESHOLD = 1.15


@dataclass(frozen=True, slots=True)
class SFLDecisionV1:
    target: str
    score: float
    noise: float
    impulse: float
    macd_level: float
    macd_slope: float
    macd_acceleration: float
    structure: float
    reason: str


def _utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def sfl_strategy_key_v1(timeframe_minutes: int) -> str:
    try:
        return SFL_STRATEGY_KEYS_V1[int(timeframe_minutes)]
    except KeyError as exc:
        raise ValueError(f"unsupported SFL timeframe: {timeframe_minutes}m") from exc


def sfl_timeframe_for_strategy_v1(strategy_key: str) -> int:
    key = str(strategy_key)
    for minutes, candidate in SFL_STRATEGY_KEYS_V1.items():
        if candidate == key:
            return minutes
    raise ValueError(f"unsupported SFL strategy: {key}")


def _clip(value: float, limit: float = 1.0) -> float:
    return max(-limit, min(limit, float(value)))


def _robust_scale(values: list[float], floor: float = 1e-9) -> float:
    clean = [abs(float(item)) for item in values if math.isfinite(float(item))]
    if not clean:
        return floor
    median = float(pd.Series(clean).median())
    return max(floor, median)


def _price_features_v1(bars: tuple[CanonicalMarketBarV2, ...]) -> tuple[float, float, float]:
    if len(bars) < 12:
        return 0.0, 1.0, 0.0
    closes = [float(item.close) for item in bars[-40:]]
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    scale = _robust_scale(deltas[-30:])
    recent = closes[-1] - closes[-4] if len(closes) >= 4 else closes[-1] - closes[-2]
    impulse = _clip(recent / max(scale * 3.0, 1e-9), 2.0)

    window = deltas[-8:]
    travel = sum(abs(item) for item in window)
    net = abs(sum(window))
    efficiency = 0.0 if travel <= 1e-9 else max(0.0, min(1.0, net / travel))
    sign_flips = 0
    nonzero = [1 if item > 0 else -1 for item in window if item != 0]
    for prior, current in zip(nonzero, nonzero[1:]):
        if prior != current:
            sign_flips += 1
    flip_noise = 0.0 if len(nonzero) < 2 else sign_flips / float(len(nonzero) - 1)
    noise = max(0.0, min(1.0, (0.65 * (1.0 - efficiency)) + (0.35 * flip_noise)))

    prior = closes[-9:-1]
    if not prior:
        structure = 0.0
    else:
        high = max(prior)
        low = min(prior)
        width = max(high - low, scale)
        if closes[-1] > high:
            structure = min(1.0, (closes[-1] - high) / width + 0.5)
        elif closes[-1] < low:
            structure = max(-1.0, -((low - closes[-1]) / width + 0.5))
        else:
            midpoint = (high + low) / 2.0
            structure = _clip((closes[-1] - midpoint) / max(width / 2.0, 1e-9))
    return float(impulse), float(noise), float(structure)


def sfl_decision_v1(
    *,
    current: str,
    spreads: tuple[float, ...],
    impulse: float,
    noise: float,
    structure: float,
) -> SFLDecisionV1:
    state = str(current).upper()
    if state not in DIRECTIONS:
        raise ValueError(f"invalid SFL state: {current}")
    if len(spreads) < 4:
        return SFLDecisionV1(state, 0.0, float(noise), float(impulse), 0.0, 0.0, 0.0, float(structure), "WARMUP")

    history = list(float(item) for item in spreads[-24:])
    scale = _robust_scale(history)
    current_spread, prior, prior2 = history[-1], history[-2], history[-3]
    level = _clip(current_spread / scale)
    slope_raw = current_spread - prior
    prior_slope = prior - prior2
    slope_scale = _robust_scale([history[i] - history[i - 1] for i in range(1, len(history))])
    slope = _clip(slope_raw / slope_scale)
    acceleration = _clip((slope_raw - prior_slope) / slope_scale)
    impulse_norm = _clip(float(impulse))
    structure_norm = _clip(float(structure))
    noise_norm = max(0.0, min(1.0, float(noise)))

    score = _clip(
        (0.30 * level)
        + (0.25 * slope)
        + (0.15 * acceleration)
        + (0.20 * impulse_norm)
        + (0.10 * structure_norm)
    )
    rapid_up = impulse_norm >= IMPULSE_ALERT_THRESHOLD or (impulse_norm >= 0.70 and slope >= 0.55)
    rapid_down = impulse_norm <= -IMPULSE_ALERT_THRESHOLD or (impulse_norm <= -0.70 and slope <= -0.55)

    if state == STATE_LONG:
        if rapid_down or score <= EXIT_THRESHOLD:
            return SFLDecisionV1(STATE_FLAT, score, noise_norm, impulse_norm, level, slope, acceleration, structure_norm, "DEFENSIVE_EXIT_LONG")
        return SFLDecisionV1(STATE_LONG, score, noise_norm, impulse_norm, level, slope, acceleration, structure_norm, "HOLD_LONG")
    if state == STATE_SHORT:
        if rapid_up or score >= -EXIT_THRESHOLD:
            return SFLDecisionV1(STATE_FLAT, score, noise_norm, impulse_norm, level, slope, acceleration, structure_norm, "DEFENSIVE_EXIT_SHORT")
        return SFLDecisionV1(STATE_SHORT, score, noise_norm, impulse_norm, level, slope, acceleration, structure_norm, "HOLD_SHORT")

    if noise_norm >= NOISE_FLAT_THRESHOLD and abs(score) < 0.72:
        return SFLDecisionV1(STATE_FLAT, score, noise_norm, impulse_norm, level, slope, acceleration, structure_norm, "NOISE_FLAT")
    if score >= ENTER_THRESHOLD or (rapid_up and score >= FAST_ENTER_THRESHOLD):
        return SFLDecisionV1(STATE_LONG, score, noise_norm, impulse_norm, level, slope, acceleration, structure_norm, "CONFIRM_LONG")
    if score <= -ENTER_THRESHOLD or (rapid_down and score <= -FAST_ENTER_THRESHOLD):
        return SFLDecisionV1(STATE_SHORT, score, noise_norm, impulse_norm, level, slope, acceleration, structure_norm, "CONFIRM_SHORT")
    return SFLDecisionV1(STATE_FLAT, score, noise_norm, impulse_norm, level, slope, acceleration, structure_norm, "WAIT_FLAT")


def _spread_history_v1(bars: tuple[CanonicalMarketBarV2, ...], *, timeframe_minutes: int):
    closed = closed_bars_v2(tuple(item.point for item in bars), market=str(bars[0].market_name), timeframe_minutes=int(timeframe_minutes))
    return macd_observations_v2(closed, timeframe_minutes=int(timeframe_minutes))


def _decision_at_v1(bars: tuple[CanonicalMarketBarV2, ...], *, timeframe_minutes: int, current: str) -> tuple[SFLDecisionV1, Macd1mClockV2]:
    observations = _spread_history_v1(bars, timeframe_minutes=timeframe_minutes)
    if len(observations) < 4:
        raise ValueError(f"SFL {timeframe_minutes}m needs MACD warmup")
    impulse, noise, structure = _price_features_v1(bars)
    decision = sfl_decision_v1(current=current, spreads=tuple(item.spread for item in observations), impulse=impulse, noise=noise, structure=structure)
    previous, latest = observations[-2], observations[-1]
    action_at = _utc(bars[-1].bar_time).replace(second=0, microsecond=0) + timedelta(minutes=1)
    clock = Macd1mClockV2(
        action_at=action_at,
        previous_macd=float(previous.macd), previous_signal=float(previous.signal), previous_spread=float(previous.spread),
        current_macd=float(latest.macd), current_signal=float(latest.signal), current_spread=float(latest.spread),
        cross_direction=None, data_gap=False,
    )
    return decision, clock


def _series_for_sfl_v1(bars: tuple[CanonicalMarketBarV2, ...], *, timeframe_minutes: int, seed_equity: float, currency: str, started_at: datetime, as_of: datetime) -> ShadowBenchmarkSeriesV2 | None:
    started, end = _utc(started_at), _utc(as_of)
    usable = [item for item in bars if started <= (_utc(item.bar_time) + timedelta(minutes=1)) <= end]
    if not usable:
        return None
    state, equity = STATE_FLAT, float(seed_equity)
    prior_price = float(usable[0].close)
    points = [ShadowEquityPointV2(closed_at=_utc(usable[0].bar_time) + timedelta(minutes=1), equity=equity, position_state=state)]
    prefix = list(item for item in bars if (_utc(item.bar_time) + timedelta(minutes=1)) < started)
    for item in usable[1:]:
        prefix.append(item)
        price = float(item.close)
        if prior_price > 0:
            equity = apply_shadow_return_v2(equity=equity, position_state=state, price_return=(price / prior_price) - 1.0)
        if len(prefix) >= 80:
            try:
                state = _decision_at_v1(tuple(prefix), timeframe_minutes=timeframe_minutes, current=state)[0].target
            except ValueError:
                pass
        at = _utc(item.bar_time) + timedelta(minutes=1)
        points.append(ShadowEquityPointV2(closed_at=at, equity=float(equity), position_state=state))
        prior_price = price
    return ShadowBenchmarkSeriesV2(strategy_key=sfl_strategy_key_v1(timeframe_minutes), execution_mode="SHADOW_ADAPTIVE", currency=str(currency), seed_equity=float(seed_equity), started_at=points[0].closed_at, points=tuple(points))


def load_sfl_series_v1(*, instrument_id: int, seed_equity: float, currency: str, started_at: datetime, as_of: datetime, db_path: str = "pricegauger.db") -> tuple[ShadowBenchmarkSeriesV2, ...]:
    started, end = _utc(started_at), _utc(as_of)
    bars = CanonicalMarketBarStoreV2(db_path).load_instrument_range(instrument_id=int(instrument_id), start=started - timedelta(days=BENCHMARK_WARMUP_DAYS), end=end, limit=BENCHMARK_MAX_1M_BARS)
    if not bars:
        return ()
    materialized = tuple(bars)
    result = []
    for minutes in SFL_TIMEFRAMES_V1:
        series = _series_for_sfl_v1(materialized, timeframe_minutes=minutes, seed_equity=seed_equity, currency=currency, started_at=started, as_of=end)
        if series is not None:
            result.append(series)
    return tuple(result)


def run_sfl_live_once_v1(enrollment: StrategyEnrollmentV2, *, db_path: str = "pricegauger.db", now: datetime | None = None, observations: tuple[PositionObservationV2, ...] | None = None) -> FastLiveCycleV2:
    if enrollment.execution_mode != EXECUTION_MODE_LIVE or not enrollment.enabled:
        raise ValueError("SFL runtime only executes active LIVE_MANAGE enrollments")
    minutes = sfl_timeframe_for_strategy_v1(enrollment.strategy_key)
    ensure_fast_live_schema_v2()
    end = _utc(now or datetime.now(timezone.utc))
    bars = CanonicalMarketBarStoreV2(db_path).load_instrument_range(instrument_id=int(enrollment.instrument_id), start=end - timedelta(days=3), end=end, limit=5_000)
    if not bars:
        raise ValueError("SFL LIVE has no canonical 1m history")
    materialized = tuple(bars)
    if observations is None:
        client = configured_client()
        if client is None:
            raise RuntimeError("Saxo client is not configured")
        observations = _position_observations_v2(client)
    observed = _exact_product_observation(enrollment, observations)
    observed_direction = _observed_direction(observed)
    state = load_fast_live_state_v2(enrollment)
    if state is None:
        _, clock = _decision_at_v1(materialized, timeframe_minutes=minutes, current=observed_direction)
        state = FastLiveStateV2(pilot_key=enrollment.pilot_key, strategy_key=enrollment.strategy_key, desired_direction=observed_direction, last_action_at=clock.action_at)
        _persist_state_v2(state)
        _persist_bootstrap_v2(enrollment, state, observed)
        return FastLiveCycleV2(enrollment.pilot_key, enrollment.strategy_key, state.desired_direction, observed_direction, None, clock.action_at, False, False, True, "BOOTSTRAP_SFL")

    if state.pending_target_direction is not None:
        if observed_direction == state.pending_target_direction:
            state = _clear_intent_v2(state, observed_direction=observed_direction)
            _persist_state_v2(state)
    elif observed_direction != state.desired_direction:
        state = _clear_intent_v2(state, observed_direction=observed_direction)
        _persist_state_v2(state)

    decision, clock = _decision_at_v1(materialized, timeframe_minutes=minutes, current=state.desired_direction)
    new_action = state.last_action_at is None or clock.action_at > state.last_action_at
    request_created = False
    reason = "NO_NEW_SFL_ACTION"
    if new_action:
        fresh = timedelta(0) <= (end - clock.action_at) <= FRESH_MAX_AGE
        if not fresh:
            state = FastLiveStateV2(pilot_key=state.pilot_key, strategy_key=state.strategy_key, desired_direction=state.desired_direction, last_action_at=clock.action_at, pending_target_direction=state.pending_target_direction, intent_event_id=state.intent_event_id, intent_signal_at=state.intent_signal_at, intent_signal=state.intent_signal, intent_previous_macd=state.intent_previous_macd, intent_previous_signal=state.intent_previous_signal, intent_current_macd=state.intent_current_macd, intent_current_signal=state.intent_current_signal)
            reason = "STALE_SFL_ACTION_SKIPPED"
        elif decision.target != state.desired_direction:
            signal = f"SFL_{minutes}M:{decision.reason}:score={decision.score:+.3f}:noise={decision.noise:.2f}:impulse={decision.impulse:+.2f}"
            state = _new_intent_state_v2(state, target=decision.target, observed_direction=observed_direction, clock=clock, signal=signal)
            equity = load_pilot_equity_v2(pilot_key=enrollment.pilot_key)
            request_created = _persist_intent_and_request_v2(enrollment=enrollment, state=state, observed=observed, observed_direction=observed_direction, budget_amount=equity.entry_budget, budget_currency=equity.currency, supersede_prior=True)
            reason = f"TARGET_{decision.target}_{decision.reason}"
        else:
            state = FastLiveStateV2(pilot_key=state.pilot_key, strategy_key=state.strategy_key, desired_direction=state.desired_direction, last_action_at=clock.action_at, pending_target_direction=state.pending_target_direction, intent_event_id=state.intent_event_id, intent_signal_at=state.intent_signal_at, intent_signal=state.intent_signal, intent_previous_macd=state.intent_previous_macd, intent_previous_signal=state.intent_previous_signal, intent_current_macd=state.intent_current_macd, intent_current_signal=state.intent_current_signal)
            reason = decision.reason

    if state.pending_target_direction is not None and observed_direction != state.pending_target_direction:
        equity = load_pilot_equity_v2(pilot_key=enrollment.pilot_key)
        continued = _persist_intent_and_request_v2(enrollment=enrollment, state=state, observed=observed, observed_direction=observed_direction, budget_amount=equity.entry_budget, budget_currency=equity.currency, supersede_prior=False)
        request_created = request_created or continued
        if continued:
            reason = "PENDING_TRANSITION_RETRY_READY"
    _persist_state_v2(state)
    return FastLiveCycleV2(enrollment.pilot_key, enrollment.strategy_key, state.desired_direction, observed_direction, state.pending_target_direction, clock.action_at, new_action, request_created, False, reason)


__all__ = [
    "SFLDecisionV1", "SFL_SERIES_VERSION_V1", "SFL_STRATEGY_KEYS_V1", "SFL_TIMEFRAMES_V1",
    "load_sfl_series_v1", "run_sfl_live_once_v1", "sfl_decision_v1", "sfl_strategy_key_v1", "sfl_timeframe_for_strategy_v1",
]
