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
from autotrader_price_stoch_v1 import (
    DEFAULT_PRICE_STOCH_CONFIG_V1,
    FLAT,
    LONG,
    SHORT,
    PRICE_STOCH_STRATEGY_V1,
    PriceStochDecisionV1,
    build_price_stoch_features_v1,
    evaluate_price_stoch_row_v1,
)
from autotrader_risk_control_v2 import PositionObservationV2, _position_observations_v2
from autotrader_mtf_entry_shadow_v2 import closed_bars_v2
from autotrader_strategy_family_v1 import FAMILY_PRICE_STOCH_V1, load_strategy_family_config_v1
from autotrader_strategy_enrollment_v2 import EXECUTION_MODE_LIVE, StrategyEnrollmentV2
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2, CanonicalMarketBarV2
from saxo_chart_live import FormingCandleStore, forming_candle_event_age_seconds
from saxo_provider import configured_client
from trading_desk import ChartBar, utc


PRICE_STOCH_LIVE_STRATEGIES_V1 = {PRICE_STOCH_STRATEGY_V1}
FORMING_MAX_AGE_SECONDS_V1 = 8.0
MAX_CANONICAL_GAP_MINUTES_V1 = 2.0


def _utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _bar_action_at(bar: CanonicalMarketBarV2) -> datetime:
    return _utc(bar.bar_time).replace(second=0, microsecond=0) + timedelta(minutes=1)


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


def _canonical_chart_bars_v1(bars: tuple[CanonicalMarketBarV2, ...]) -> list[ChartBar]:
    return [
        ChartBar(
            market=str(item.market_name),
            bar_time=str(item.bar_time),
            open=float(item.open),
            high=float(item.high),
            low=float(item.low),
            close=float(item.close),
            volume=None if item.volume is None else float(item.volume),
        )
        for item in bars
    ]


def _live_bars_and_action_v1(
    enrollment: StrategyEnrollmentV2,
    bars: tuple[CanonicalMarketBarV2, ...],
    *,
    db_path: str,
    now: datetime,
    timeframe_minutes: int = 1,
) -> tuple[tuple[ChartBar, ...], datetime, bool, bool]:
    """Append only a fresh exact-product forming candle for intra-minute scouting."""

    if not bars:
        raise ValueError("price/stoch LIVE has no canonical history")
    minutes = max(1, int(timeframe_minutes))
    one_minute = _canonical_chart_bars_v1(bars)
    chart_bars = list(closed_bars_v2(tuple((item.bar_time, item.close) for item in one_minute), market=enrollment.market_name, timeframe_minutes=minutes)) if minutes > 1 else one_minute
    action_at = _bar_action_at(bars[-1])
    used_forming = False

    try:
        candle = FormingCandleStore(db_path).load(market=enrollment.market_name)
    except Exception:
        candle = None
    if candle is not None:
        age = forming_candle_event_age_seconds(candle, now=now)
        exact_product = (
            int(candle.uic) == int(enrollment.uic)
            and str(candle.asset_type) == str(enrollment.asset_type)
        )
        candle_at = _utc(candle.bar_time)
        last_closed_at = _utc(bars[-1].bar_time)
        if (
            exact_product
            and age is not None
            and 0.0 <= age <= FORMING_MAX_AGE_SECONDS_V1
            and candle_at > last_closed_at
        ):
            forming = ChartBar(
                market=enrollment.market_name,
                bar_time=candle_at.isoformat(),
                open=float(candle.open),
                high=float(candle.high),
                low=float(candle.low),
                close=float(candle.close),
                volume=None if candle.volume is None else float(candle.volume),
            )
            if minutes == 1:
                chart_bars.append(forming)
            else:
                bucket_start = candle_at.replace(second=0, microsecond=0) - timedelta(minutes=candle_at.minute % minutes)
                members = [item for item in one_minute if _utc(item.bar_time) >= bucket_start]
                members.append(forming)
                chart_bars.append(ChartBar(
                    market=enrollment.market_name,
                    bar_time=bucket_start.isoformat(),
                    open=float(members[0].open),
                    high=max(float(item.high) for item in members),
                    low=min(float(item.low) for item in members),
                    close=float(members[-1].close),
                    volume=None,
                ))
            action_at = _utc(candle.updated_at)
            used_forming = True

    data_gap = False
    if len(bars) >= 2:
        gap_minutes = (
            _bar_action_at(bars[-1]) - _bar_action_at(bars[-2])
        ).total_seconds() / 60.0
        data_gap = gap_minutes > MAX_CANONICAL_GAP_MINUTES_V1
    return tuple(chart_bars), action_at, data_gap, used_forming


def _clock_v1(*, action_at: datetime, features, data_gap: bool) -> Macd1mClockV2:
    current = features.iloc[-1]
    previous = features.iloc[-2] if len(features) >= 2 else current
    current_value = float(current.get("PRICE_FAST_SLOPE_PCT", 0.0) or 0.0)
    previous_value = float(previous.get("PRICE_FAST_SLOPE_PCT", current_value) or current_value)
    current_threshold = float(current.get("PRICE_THRESHOLD_PCT", 0.0) or 0.0)
    previous_threshold = float(previous.get("PRICE_THRESHOLD_PCT", current_threshold) or current_threshold)
    return Macd1mClockV2(
        action_at=action_at,
        previous_macd=previous_value,
        previous_signal=previous_threshold,
        previous_spread=previous_value - previous_threshold,
        current_macd=current_value,
        current_signal=current_threshold,
        current_spread=current_value - current_threshold,
        cross_direction=None,
        data_gap=bool(data_gap),
    )


def _evidence_v1(decision: PriceStochDecisionV1, *, used_forming: bool) -> str:
    scout = (
        "UP" if decision.stochastic_scout > 0
        else "DOWN" if decision.stochastic_scout < 0
        else "NEUTRAL"
    )
    macd = (
        "UP" if decision.macd_direction > 0
        else "DOWN" if decision.macd_direction < 0
        else "NEUTRAL"
    )
    return (
        f"state={decision.state};price_fast={decision.price_fast_slope_pct:+.4f}%/bar;"
        f"price_slow={decision.price_slow_slope_pct:+.4f}%/bar;"
        f"threshold={decision.price_threshold_pct:.4f}%;"
        f"stoch_k={decision.stochastic_k:.2f};"
        f"stoch_scout={scout};stoch_align={decision.stochastic_alignment}/3;"
        f"angles={decision.stochastic_angle_1:+.1f}/{decision.stochastic_angle_3:+.1f}/"
        f"{decision.stochastic_angle_5:+.1f};macd={macd};forming={int(used_forming)}"
    )


def _advance_state_v1(state: FastLiveStateV2, *, action_at: datetime) -> FastLiveStateV2:
    return replace(state, last_action_at=action_at)


def run_price_stoch_live_once_v1(
    enrollment: StrategyEnrollmentV2,
    *,
    db_path: str = "pricegauger.db",
    now: datetime | None = None,
    observations: tuple[PositionObservationV2, ...] | None = None,
) -> FastLiveCycleV2:
    """Run price-first + stochastic half-parade through the hardened executor.

    Strategy authority stops at durable target intent. All actual Saxo execution still
    goes through the existing CLOSE -> confirmed FLAT -> OPEN lifecycle.
    """

    if enrollment.execution_mode != EXECUTION_MODE_LIVE or not enrollment.enabled:
        raise ValueError("price/stoch runtime only executes active LIVE_MANAGE enrollments")
    if enrollment.strategy_key not in PRICE_STOCH_LIVE_STRATEGIES_V1:
        raise ValueError("price/stoch runtime received an unsupported strategy")

    family_config = load_strategy_family_config_v1(
        enrollment.pilot_key,
        strategy_key=enrollment.strategy_key,
    )
    if family_config is None or family_config.family != FAMILY_PRICE_STOCH_V1:
        raise ValueError("Price + Stoch family configuration is missing")
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
        raise ValueError("price/stoch LIVE needs at least 40 closed canonical 1m bars")

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
        timeframe_minutes=timeframe_minutes,
    )
    features = build_price_stoch_features_v1(
        live_bars,
        config=DEFAULT_PRICE_STOCH_CONFIG_V1,
    )
    if features.empty:
        raise ValueError("price/stoch LIVE produced no feature rows")
    clock = _clock_v1(action_at=action_at, features=features, data_gap=data_gap)

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
            "BOOTSTRAP_PRICE_STOCH",
        )

    if state.pending_target_direction is not None and observed_direction == state.pending_target_direction:
        state = _clear_intent_v2(state, observed_direction=observed_direction)
        _persist_state_v2(state)
    elif state.pending_target_direction is None and observed_direction != state.desired_direction:
        # External/manual/risk position changes are adopted as observation. No stale
        # strategy state may immediately replay an old direction into a broker order.
        state = _clear_intent_v2(state, observed_direction=observed_direction)
        _persist_state_v2(state)

    new_action = state.last_action_at is None or action_at > state.last_action_at
    request_created = False
    reason = "NO_NEW_PRICE_STOCH_ACTION"

    if new_action:
        fresh = timedelta(0) <= (end - action_at) <= FRESH_MAX_AGE
        if not fresh:
            state = _advance_state_v1(state, action_at=action_at)
            reason = "STALE_PRICE_STOCH_ACTION_SKIPPED"
        elif data_gap:
            state = _advance_state_v1(state, action_at=action_at)
            reason = "PRICE_STOCH_DATA_GAP_PRIMED"
        else:
            decision = evaluate_price_stoch_row_v1(
                features.iloc[-1],
                current_target=_target_number(state.desired_direction),
                config=DEFAULT_PRICE_STOCH_CONFIG_V1,
            )
            candidate = _target_word(decision.target)
            if candidate != state.desired_direction:
                signal = (
                    f"PRICE_STOCH:{candidate}:{_evidence_v1(decision, used_forming=used_forming)};"
                    f"reason={decision.reason}"
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
    "FORMING_MAX_AGE_SECONDS_V1",
    "PRICE_STOCH_LIVE_STRATEGIES_V1",
    "PRICE_STOCH_STRATEGY_V1",
    "run_price_stoch_live_once_v1",
]
