from __future__ import annotations

from datetime import datetime, timedelta, timezone

from autotrader_fast_live_runtime_v2 import (
    DIRECTION_FLAT,
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
from autotrader_overseer_performance_series_v1 import load_overseer_performance_series_v1
from autotrader_overseer_performance_v1 import OVERSEER_PERFORMANCE_STRATEGY_KEY_V1
from autotrader_pilot_equity_v2 import load_pilot_equity_v2
from autotrader_risk_control_v2 import PositionObservationV2, _position_observations_v2
from autotrader_strategy_enrollment_v2 import EXECUTION_MODE_LIVE, StrategyEnrollmentV2
from autotrader_strategy_series_store_v1 import load_persisted_strategy_series_v1
from saxo_provider import configured_client


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _latest_overseer_target_v1(enrollment: StrategyEnrollmentV2):
    series = load_persisted_strategy_series_v1(
        account_id=enrollment.account_id,
        uic=enrollment.uic,
        asset_type=enrollment.asset_type,
        instrument_id=enrollment.instrument_id,
        pilot_equivalent=False,
    )
    experts = tuple(item for item in series if item.strategy_key != OVERSEER_PERFORMANCE_STRATEGY_KEY_V1)
    replay = load_overseer_performance_series_v1(experts)
    if replay is None or not replay.points:
        raise ValueError("Overseer has no aligned Strategy Lab expert evidence")
    point = replay.points[-1]
    return str(point.position_state), _utc(point.closed_at)


def run_overseer_live_once_v1(
    enrollment: StrategyEnrollmentV2,
    *,
    db_path: str = "pricegauger.db",
    now: datetime | None = None,
    observations: tuple[PositionObservationV2, ...] | None = None,
) -> FastLiveCycleV2:
    """Run selectable Overseer without bypassing the common execution lifecycle.

    The runtime never changes enrollment.strategy_key and never posts to Saxo. It turns
    the no-lookahead Strategy Lab meta-policy target into the same durable intent/request
    contract used by other AutoManage models.
    """
    if enrollment.execution_mode != EXECUTION_MODE_LIVE or not enrollment.enabled:
        raise ValueError("Overseer runtime only executes active LIVE_MANAGE enrollments")
    if enrollment.strategy_key != OVERSEER_PERFORMANCE_STRATEGY_KEY_V1:
        raise ValueError("Overseer runtime received an unsupported strategy")
    ensure_fast_live_schema_v2()
    end = _utc(now or datetime.now(timezone.utc))
    candidate, action_at = _latest_overseer_target_v1(enrollment)
    if candidate not in {"LONG", "SHORT", "FLAT"}:
        candidate = DIRECTION_FLAT
    if end - action_at > FRESH_MAX_AGE or action_at > end:
        candidate = DIRECTION_FLAT

    client = configured_client()
    if observations is None:
        if client is None:
            raise RuntimeError("Saxo client is not configured")
        observations = _position_observations_v2(client)
    observed = _exact_product_observation(enrollment, observations)
    observed_direction = _observed_direction(observed)
    clock = Macd1mClockV2(action_at, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, None, False)
    state = load_fast_live_state_v2(enrollment)
    if state is None:
        state = FastLiveStateV2(enrollment.pilot_key, enrollment.strategy_key, observed_direction, action_at)
        _persist_state_v2(state)
        _persist_bootstrap_v2(enrollment, state, observed)
        return FastLiveCycleV2(enrollment.pilot_key, enrollment.strategy_key, observed_direction, observed_direction, None, action_at, False, False, True, "BOOTSTRAP_OVERSEER")

    if state.pending_target_direction is not None and observed_direction == state.pending_target_direction:
        state = _clear_intent_v2(state, observed_direction=observed_direction)
    elif state.pending_target_direction is None and observed_direction != state.desired_direction:
        state = _clear_intent_v2(state, observed_direction=observed_direction)

    request_created = False
    processed = state.last_action_at is None or action_at > state.last_action_at
    reason = "NO_NEW_OVERSEER_ACTION"
    if processed and candidate != state.desired_direction:
        state = _new_intent_state_v2(
            state,
            target=candidate,
            observed_direction=observed_direction,
            clock=clock,
            signal=f"OVERSEER:{candidate}",
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
        reason = f"TARGET_{candidate}"
    elif processed:
        state = FastLiveStateV2(
            state.pilot_key, state.strategy_key, state.desired_direction, action_at,
            state.pending_target_direction, state.intent_event_id, state.intent_signal_at,
            state.intent_signal, state.intent_previous_macd, state.intent_previous_signal,
            state.intent_current_macd, state.intent_current_signal,
        )
        reason = "TARGET_UNCHANGED"

    if state.pending_target_direction is not None and observed_direction != state.pending_target_direction:
        equity = load_pilot_equity_v2(pilot_key=enrollment.pilot_key)
        request_created = _persist_intent_and_request_v2(
            enrollment=enrollment, state=state, observed=observed,
            observed_direction=observed_direction, budget_amount=equity.entry_budget,
            budget_currency=equity.currency, supersede_prior=False,
        ) or request_created
    _persist_state_v2(state)
    return FastLiveCycleV2(enrollment.pilot_key, enrollment.strategy_key, state.desired_direction, observed_direction, state.pending_target_direction, action_at, processed, request_created, False, reason)


__all__ = ["run_overseer_live_once_v1"]
