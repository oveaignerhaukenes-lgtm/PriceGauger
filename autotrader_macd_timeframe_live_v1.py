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
    _persist_intent_and_request_v2,
    _persist_state_v2,
    ensure_fast_live_schema_v2,
    fast_request_action_v2,
    load_fast_live_state_v2,
)
from autotrader_macd_binary_execution_v1 import ensure_binary_macd_max_sizing_v1
from autotrader_macd_flip_policy_v2 import MACD_FLIP_STRATEGY_V2
from autotrader_macd_timeframe_controls_v1 import macd_control_strategy_key_v1
from autotrader_mtf_entry_shadow_v2 import closed_bars_v2, macd_observations_v2
from autotrader_pilot_equity_v2 import load_pilot_equity_v2
from autotrader_risk_control_v2 import PositionObservationV2, _position_observations_v2
from autotrader_strategy_enrollment_v2 import EXECUTION_MODE_LIVE, StrategyEnrollmentV2
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2, CanonicalMarketBarV2
from database import connect
from saxo_provider import configured_client


MACD_1M_CONTROL_STRATEGY_KEY_V1 = "macd-1m-flip-control-shadow-v1"
LIVE_MACD_CONTROL_TIMEFRAMES_V1 = (1, 2, 5, 15, 30)
LIVE_MACD_CONTROL_STRATEGIES_V1 = {
    MACD_1M_CONTROL_STRATEGY_KEY_V1: 1,
    macd_control_strategy_key_v1(2): 2,
    macd_control_strategy_key_v1(5): 5,
    macd_control_strategy_key_v1(15): 15,
    MACD_FLIP_STRATEGY_V2: 30,
}

MACD_WARMUP_LOOKBACK_V1 = timedelta(days=14)
MACD_WARMUP_MAX_BARS_V1 = 20_000
_RETRYABLE_TERMINAL_REQUEST_STATUSES_V1 = ("BLOCKED", "REJECTED")


def _utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def live_macd_control_timeframe_v1(strategy_key: str) -> int:
    try:
        return int(LIVE_MACD_CONTROL_STRATEGIES_V1[str(strategy_key)])
    except KeyError as exc:
        raise ValueError(f"unsupported LIVE MACD control strategy: {strategy_key}") from exc


def _timeframe_clock_v1(
    bars: tuple[CanonicalMarketBarV2, ...],
    *,
    timeframe_minutes: int,
) -> Macd1mClockV2:
    """Build the execution clock strictly from completed timeframe bars.

    A simple MACD-N control must make at most one new decision per completed N-minute
    candle. Forming candles are intentionally excluded because their MACD spread can
    cross back and forth before close and cause false live reversals.
    """
    minutes = int(timeframe_minutes)
    if not bars:
        raise ValueError("MACD timeframe LIVE has no canonical history")
    closed = closed_bars_v2(
        tuple(item.point for item in bars),
        market=str(bars[0].market_name),
        timeframe_minutes=minutes,
    )
    observations = macd_observations_v2(closed, timeframe_minutes=minutes)
    if len(observations) < 2:
        raise ValueError(f"MACD {minutes}m LIVE needs enough closed history for MACD 12/26/9")
    previous, current = observations[-2], observations[-1]
    expected = timedelta(minutes=minutes)
    data_gap = current.closed_at - previous.closed_at != expected
    cross = None
    if not data_gap:
        if previous.spread <= 0.0 < current.spread:
            cross = DIRECTION_LONG
        elif previous.spread >= 0.0 > current.spread:
            cross = DIRECTION_SHORT
    return Macd1mClockV2(
        action_at=_utc(current.closed_at),
        previous_macd=float(previous.macd),
        previous_signal=float(previous.signal),
        previous_spread=float(previous.spread),
        current_macd=float(current.macd),
        current_signal=float(current.signal),
        current_spread=float(current.spread),
        cross_direction=cross,
        data_gap=bool(data_gap),
    )


def _matching_intent_request_exists_v1(
    enrollment: StrategyEnrollmentV2,
    state: FastLiveStateV2,
    *,
    observed_direction: str,
) -> bool:
    if state.intent_signal_at is None:
        return False
    desired = state.pending_target_direction or state.desired_direction
    action = fast_request_action_v2(observed_direction, desired)
    if action is None:
        return False
    with connect() as db:
        row = db.execute(
            """
            SELECT 1
            FROM pg_v2_autotrader_execution_requests
            WHERE pilot_key = ? AND strategy_key = ? AND action = ?
              AND desired_direction = ? AND signal_at = ?
            LIMIT 1
            """,
            (
                enrollment.pilot_key,
                enrollment.strategy_key,
                action,
                desired,
                state.intent_signal_at,
            ),
        ).fetchone()
    return row is not None


def _rearm_retryable_terminal_request_v1(
    enrollment: StrategyEnrollmentV2,
    state: FastLiveStateV2,
    *,
    observed_direction: str,
) -> bool:
    """Re-arm only a known terminal request through the normal hardened lifecycle."""
    if state.intent_signal_at is None:
        return False
    desired = state.pending_target_direction or state.desired_direction
    action = fast_request_action_v2(observed_direction, desired)
    if action is None:
        return False
    with connect() as db:
        cursor = db.execute(
            """
            UPDATE pg_v2_autotrader_execution_requests
            SET status = 'PENDING', block_reason = NULL, order_id = NULL, updated_at = now()
            WHERE request_id = (
                SELECT request_id
                FROM pg_v2_autotrader_execution_requests
                WHERE pilot_key = ? AND strategy_key = ? AND action = ?
                  AND desired_direction = ? AND signal_at = ?
                  AND status IN ('BLOCKED', 'REJECTED')
                ORDER BY updated_at DESC, created_at DESC
                LIMIT 1
            )
            """,
            (
                enrollment.pilot_key,
                enrollment.strategy_key,
                action,
                desired,
                state.intent_signal_at,
            ),
        )
        changed = int(cursor.rowcount or 0) > 0
    return changed


def _persist_binary_macd_intent_v1(
    *,
    enrollment: StrategyEnrollmentV2,
    state: FastLiveStateV2,
    observed: PositionObservationV2 | None,
    observed_direction: str,
    budget_amount: float,
    budget_currency: str,
    supersede_prior: bool,
) -> bool:
    existed_before = _matching_intent_request_exists_v1(
        enrollment,
        state,
        observed_direction=observed_direction,
    )
    nominal_created = _persist_intent_and_request_v2(
        enrollment=enrollment,
        state=state,
        observed=observed,
        observed_direction=observed_direction,
        budget_amount=budget_amount,
        budget_currency=budget_currency,
        supersede_prior=supersede_prior,
    )
    rearmed = _rearm_retryable_terminal_request_v1(
        enrollment,
        state,
        observed_direction=observed_direction,
    )
    return bool(rearmed or (nominal_created and not existed_before))


def _advance_action_state_v1(state: FastLiveStateV2, *, action_at: datetime) -> FastLiveStateV2:
    return FastLiveStateV2(
        pilot_key=state.pilot_key,
        strategy_key=state.strategy_key,
        desired_direction=state.desired_direction,
        last_action_at=action_at,
        pending_target_direction=state.pending_target_direction,
        intent_event_id=state.intent_event_id,
        intent_signal_at=state.intent_signal_at,
        intent_signal=state.intent_signal,
        intent_previous_macd=state.intent_previous_macd,
        intent_previous_signal=state.intent_previous_signal,
        intent_current_macd=state.intent_current_macd,
        intent_current_signal=state.intent_current_signal,
    )


def run_macd_timeframe_live_once_v1(
    enrollment: StrategyEnrollmentV2,
    *,
    db_path: str = "pricegauger.db",
    now: datetime | None = None,
    observations: tuple[PositionObservationV2, ...] | None = None,
) -> FastLiveCycleV2:
    """Run one binary MACD LONG/SHORT control from completed timeframe bars only.

    MACD1/2/5/15/30 each receive at most one new signal opportunity per completed
    timeframe candle. This prevents provisional intrabar crosses from causing repeated
    broker reversals. Execution safety remains delegated to the existing durable
    CLOSE -> confirmed FLAT -> OPEN lifecycle.
    """
    if enrollment.execution_mode != EXECUTION_MODE_LIVE or not enrollment.enabled:
        raise ValueError("MACD timeframe runtime only executes active LIVE_MANAGE enrollments")
    minutes = live_macd_control_timeframe_v1(enrollment.strategy_key)
    ensure_fast_live_schema_v2()

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
        raise ValueError(f"MACD {minutes}m LIVE has no exact canonical 1m history")
    clock = _timeframe_clock_v1(tuple(bars), timeframe_minutes=minutes)

    if observations is None:
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
            "BOOTSTRAP_LIVE_PROBE",
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
    reason = f"NO_NEW_{minutes}M_ACTION"

    if new_action:
        fresh = timedelta(0) <= (end - clock.action_at) <= FRESH_MAX_AGE
        if not fresh:
            state = _advance_action_state_v1(state, action_at=clock.action_at)
            _persist_state_v2(state)
            reason = f"STALE_{minutes}M_ACTION_SKIPPED"
        elif clock.data_gap:
            state = _advance_action_state_v1(state, action_at=clock.action_at)
            _persist_state_v2(state)
            reason = f"CLOSED_{minutes}M_PRIMED"
        elif clock.cross_direction is not None and clock.cross_direction != state.desired_direction:
            target = clock.cross_direction
            signal = f"CLOSED_CROSS_{minutes}M_{'UP' if target == DIRECTION_LONG else 'DOWN'}"
            state = _new_intent_state_v2(
                state,
                target=target,
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
            reason = f"TARGET_{target}"
        else:
            state = _advance_action_state_v1(state, action_at=clock.action_at)
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
    "LIVE_MACD_CONTROL_STRATEGIES_V1",
    "LIVE_MACD_CONTROL_TIMEFRAMES_V1",
    "MACD_1M_CONTROL_STRATEGY_KEY_V1",
    "MACD_WARMUP_LOOKBACK_V1",
    "MACD_WARMUP_MAX_BARS_V1",
    "live_macd_control_timeframe_v1",
    "run_macd_timeframe_live_once_v1",
]
