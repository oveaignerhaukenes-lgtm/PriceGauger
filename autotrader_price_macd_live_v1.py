from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

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
    _persist_state_v2,
    ensure_fast_live_schema_v2,
    load_fast_live_state_v2,
)
from autotrader_macd_binary_execution_v1 import ensure_binary_macd_max_sizing_v1
from autotrader_macd_timeframe_live_v1 import (
    MACD_WARMUP_LOOKBACK_V1,
    MACD_WARMUP_MAX_BARS_V1,
    _persist_binary_macd_intent_v1,
)
from autotrader_pilot_equity_v2 import load_pilot_equity_v2
from autotrader_price_macd_v1 import (
    DEFAULT_PRICE_MACD_CONFIG_V1,
    FLAT,
    LONG,
    SHORT,
    build_price_macd_features_v1,
    evaluate_price_macd_row_v1,
)
from autotrader_price_stoch_live_v1 import _live_bars_and_action_v1
from autotrader_risk_control_v2 import PositionObservationV2, _position_observations_v2
from autotrader_strategy_enrollment_v2 import EXECUTION_MODE_LIVE, StrategyEnrollmentV2
from autotrader_strategy_family_v1 import (
    FAMILY_PRICE_MACD_STRATEGY_V1,
    FAMILY_PRICE_MACD_V1,
    load_strategy_family_config_v1,
)
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from saxo_provider import configured_client


PRICE_MACD_LIVE_STRATEGIES_V1 = {FAMILY_PRICE_MACD_STRATEGY_V1}


def _utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _bar_action_at(item) -> datetime:
    return _utc(item.bar_time).replace(second=0, microsecond=0) + timedelta(minutes=1)


def _target_word(value: int) -> str:
    if int(value) > 0:
        return DIRECTION_LONG
    if int(value) < 0:
        return DIRECTION_SHORT
    return DIRECTION_FLAT


def _target_number(value: str) -> int:
    word = str(value).upper()
    if word == DIRECTION_LONG:
        return LONG
    if word == DIRECTION_SHORT:
        return SHORT
    return FLAT


def _clock_from_features_v1(features, *, action_at: datetime, data_gap: bool) -> Macd1mClockV2:
    current = features.iloc[-1]
    previous = features.iloc[-2] if len(features) >= 2 else current
    current_spread = float(current.get("MACD_SPREAD", 0.0) or 0.0)
    previous_spread = float(previous.get("MACD_SPREAD", current_spread) or current_spread)
    cross_value = int(current.get("MACD_CROSS", 0) or 0)
    cross = DIRECTION_LONG if cross_value > 0 else DIRECTION_SHORT if cross_value < 0 else None
    return Macd1mClockV2(
        action_at=action_at,
        previous_macd=previous_spread,
        previous_signal=0.0,
        previous_spread=previous_spread,
        current_macd=current_spread,
        current_signal=0.0,
        current_spread=current_spread,
        cross_direction=cross,
        data_gap=bool(data_gap),
    )


def _advance_state_v1(state: FastLiveStateV2, *, action_at: datetime) -> FastLiveStateV2:
    return replace(state, last_action_at=action_at)


def run_price_macd_live_once_v1(
    enrollment: StrategyEnrollmentV2,
    *,
    db_path: str = "pricegauger.db",
    now: datetime | None = None,
    observations: tuple[PositionObservationV2, ...] | None = None,
) -> FastLiveCycleV2:
    if enrollment.execution_mode != EXECUTION_MODE_LIVE or not enrollment.enabled:
        raise ValueError("Price + MACD runtime only executes active LIVE enrollments")
    if enrollment.strategy_key not in PRICE_MACD_LIVE_STRATEGIES_V1:
        raise ValueError("Price + MACD runtime received an unsupported strategy")

    family_config = load_strategy_family_config_v1(
        enrollment.pilot_key,
        strategy_key=enrollment.strategy_key,
    )
    if family_config is None or family_config.family != FAMILY_PRICE_MACD_V1:
        raise ValueError("Price + MACD family configuration is missing")
    timeframe_minutes = int(family_config.timeframe_minutes)

    ensure_fast_live_schema_v2()
    client = configured_client()
    if client is not None:
        ensure_binary_macd_max_sizing_v1(enrollment, client)

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
    if len(eligible) < 40:
        raise ValueError("Price + MACD LIVE needs at least 40 closed canonical 1m bars")

    if observations is None:
        if client is None:
            raise RuntimeError("Saxo client is not configured")
        observations = _position_observations_v2(client)
    observed = _exact_product_observation(enrollment, observations)
    observed_direction = _observed_direction(observed)

    live_bars, action_at, data_gap, used_forming = _live_bars_and_action_v1(
        enrollment,
        eligible,
        db_path=db_path,
        now=end,
    )
    features = build_price_macd_features_v1(
        live_bars,
        timeframe_minutes=timeframe_minutes,
        config=DEFAULT_PRICE_MACD_CONFIG_V1,
    )
    if features.empty:
        raise ValueError("Price + MACD LIVE produced no feature rows")
    clock = _clock_from_features_v1(features, action_at=action_at, data_gap=data_gap)

    state = load_fast_live_state_v2(enrollment)
    if state is None:
        state = FastLiveStateV2(
            pilot_key=enrollment.pilot_key,
            strategy_key=enrollment.strategy_key,
            desired_direction=observed_direction,
            last_action_at=action_at,
        )
        _persist_state_v2(state)
        _persist_bootstrap_v2(enrollment, state, observed)
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
            "BOOTSTRAP_PRICE_MACD",
        )

    if state.pending_target_direction is not None and observed_direction == state.pending_target_direction:
        state = _clear_intent_v2(state, observed_direction=observed_direction)
        _persist_state_v2(state)
    elif state.pending_target_direction is None and observed_direction != state.desired_direction:
        state = _clear_intent_v2(state, observed_direction=observed_direction)
        _persist_state_v2(state)

    new_action = state.last_action_at is None or action_at > state.last_action_at
    request_created = False
    reason = "NO_NEW_PRICE_MACD_ACTION"

    if new_action:
        fresh = timedelta(0) <= (end - action_at) <= FRESH_MAX_AGE
        if not fresh:
            state = _advance_state_v1(state, action_at=action_at)
            reason = "STALE_PRICE_MACD_ACTION_SKIPPED"
        elif data_gap:
            state = _advance_state_v1(state, action_at=action_at)
            reason = "PRICE_MACD_DATA_GAP_PRIMED"
        else:
            decision = evaluate_price_macd_row_v1(
                features.iloc[-1],
                current_target=_target_number(state.desired_direction),
                config=DEFAULT_PRICE_MACD_CONFIG_V1,
            )
            candidate = _target_word(decision.target)
            if candidate != state.desired_direction:
                signal = (
                    f"PRICE_MACD:{timeframe_minutes}m:{candidate};"
                    f"state={decision.state};"
                    f"price_fast={decision.price_fast_slope_pct:+.5f};"
                    f"price_slow={decision.price_slow_slope_pct:+.5f};"
                    f"threshold={decision.price_threshold_pct:.5f};"
                    f"macd_direction={decision.macd_direction};macd_cross={decision.macd_cross};"
                    f"forming={int(used_forming)};reason={decision.reason}"
                )
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
                reason = f"TARGET_{candidate}_{decision.state}"
            else:
                state = _advance_state_v1(state, action_at=action_at)
                reason = f"TARGET_UNCHANGED_{decision.state}"

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
        action_at=action_at,
        processed=new_action,
        request_created=request_created,
        bootstrap=False,
        reason=reason,
    )


__all__ = [
    "PRICE_MACD_LIVE_STRATEGIES_V1",
    "run_price_macd_live_once_v1",
]
