from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

from autotrader_ai_baseline_v1 import (
    STRATEGY_KEY as AI_BASELINE_STRATEGY_V1,
    ai_decision_is_fresh_v1,
    load_latest_ai_decision_v1,
)
from autotrader_fast_live_runtime_v2 import (
    DIRECTION_FLAT,
    FastLiveCycleV2,
    FastLiveStateV2,
    _clear_intent_v2,
    _exact_product_observation,
    _observed_direction,
    _persist_bootstrap_v2,
    _persist_intent_and_request_v2,
    _persist_state_v2,
    ensure_fast_live_schema_v2,
    load_fast_live_state_v2,
)
from autotrader_pilot_equity_v2 import load_pilot_equity_v2
from autotrader_risk_control_v2 import PositionObservationV2, _position_observations_v2
from autotrader_strategy_enrollment_v2 import EXECUTION_MODE_LIVE, StrategyEnrollmentV2
from saxo_provider import configured_client


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _ai_intent_state_v1(
    state: FastLiveStateV2,
    *,
    observed_direction: str,
    target: str,
    action_at: datetime,
    context_hash: str,
) -> FastLiveStateV2:
    event_id = str(
        uuid5(
            NAMESPACE_URL,
            f"ai-baseline-intent|{state.pilot_key}|{action_at.isoformat()}|{target}|{context_hash}",
        )
    )
    return replace(
        state,
        desired_direction=target,
        pending_target_direction=None if target == observed_direction else target,
        intent_event_id=event_id,
        intent_signal_at=action_at,
        intent_signal=f"AI_{target}",
        intent_previous_macd=None,
        intent_previous_signal=None,
        intent_current_macd=None,
        intent_current_signal=None,
        last_action_at=action_at,
    )


def run_ai_live_strategy_once_v1(
    enrollment: StrategyEnrollmentV2,
    *,
    db_path: str = "pricegauger.db",
    now: datetime | None = None,
    observations: tuple[PositionObservationV2, ...] | None = None,
) -> FastLiveCycleV2:
    """Consume one persisted AI target through the normal AutoManager request path.

    GPT never reaches Saxo here. The AI baseline only supplies ``LONG/SHORT/FLAT``;
    the existing execution request, close bridge, OPEN sizing, Margin Envelope,
    Product Admission, Saxo precheck and durable-submit machinery remain authoritative.
    """
    _ = db_path
    if enrollment.execution_mode != EXECUTION_MODE_LIVE or not enrollment.enabled:
        raise ValueError("AI runtime only executes active LIVE_MANAGE enrollments")
    if enrollment.strategy_key != AI_BASELINE_STRATEGY_V1:
        raise ValueError("AI runtime received unsupported strategy")
    ensure_fast_live_schema_v2()

    current_time = _utc(now or datetime.now(timezone.utc))
    if observations is None:
        client = configured_client()
        if client is None:
            raise RuntimeError("Saxo client is not configured")
        observations = _position_observations_v2(client)
    observed = _exact_product_observation(enrollment, observations)
    observed_direction = _observed_direction(observed)

    decision = load_latest_ai_decision_v1(int(enrollment.instrument_id))
    action_at = current_time if decision is None else decision.action_at
    state = load_fast_live_state_v2(enrollment)
    if state is None:
        state = FastLiveStateV2(
            pilot_key=enrollment.pilot_key,
            strategy_key=enrollment.strategy_key,
            desired_direction=observed_direction,
            last_action_at=None if decision is None else decision.action_at,
        )
        _persist_state_v2(state)
        _persist_bootstrap_v2(enrollment, state, observed)
        return FastLiveCycleV2(
            enrollment.pilot_key,
            enrollment.strategy_key,
            state.desired_direction,
            observed_direction,
            None,
            action_at,
            False,
            False,
            True,
            "BOOTSTRAP_NO_REPLAY",
        )

    # Keep the same adoption semantics as the fast technical strategies: if a manual
    # or risk-origin change occurred and no strategy transition is pending, adopt the
    # newly observed exposure instead of resurrecting a stale AI target.
    if state.pending_target_direction is not None:
        if observed_direction == state.pending_target_direction:
            state = _clear_intent_v2(state, observed_direction=observed_direction)
            _persist_state_v2(state)
    elif observed_direction != state.desired_direction:
        state = _clear_intent_v2(state, observed_direction=observed_direction)
        _persist_state_v2(state)

    request_created = False
    reason = "WAIT_AI_DECISION"
    if decision is not None and (
        state.last_action_at is None or decision.action_at > state.last_action_at
    ):
        if not ai_decision_is_fresh_v1(decision, now=current_time):
            state = replace(state, last_action_at=decision.action_at)
            _persist_state_v2(state)
            reason = "STALE_AI_DECISION_SKIPPED"
        else:
            target = decision.target_direction
            if target != state.desired_direction:
                state = _ai_intent_state_v1(
                    state,
                    observed_direction=observed_direction,
                    target=target,
                    action_at=decision.action_at,
                    context_hash=decision.context_hash,
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
                state = replace(state, last_action_at=decision.action_at)
                _persist_state_v2(state)
                reason = "TARGET_UNCHANGED"

    # Carry a requested reversal across CLOSE -> confirmed FLAT -> OPEN without asking
    # GPT again. Downstream execution still proves settlement and all entry gates.
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
        if decision is None or not (
            state.last_action_at is None or decision.action_at > state.last_action_at
        ):
            reason = "PENDING_TRANSITION_CONTINUED"

    _persist_state_v2(state)
    return FastLiveCycleV2(
        pilot_key=enrollment.pilot_key,
        strategy_key=enrollment.strategy_key,
        desired_direction=state.desired_direction,
        observed_direction=observed_direction,
        pending_target_direction=state.pending_target_direction,
        action_at=action_at,
        processed=decision is not None,
        request_created=request_created,
        bootstrap=False,
        reason=reason,
    )


__all__ = ["run_ai_live_strategy_once_v1"]
