from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from autotrader_fast_live_runtime_v2 import (
    FastLiveCycleV2,
    _exact_product_observation,
    _observed_direction,
    load_fast_live_state_v2,
)
from autotrader_macd_normalized_live_v1 import (
    MACD_NORMALIZED_LIVE_STRATEGIES_V1,
    run_macd_normalized_live_once_v1 as _run_macd_normalized_live_once_v1,
)
from autotrader_macd_timeframe_live_v1 import (
    _matching_intent_request_exists_v1,
    _rearm_retryable_terminal_request_v1,
)
from autotrader_risk_control_v2 import PositionObservationV2, _position_observations_v2
from autotrader_strategy_enrollment_v2 import StrategyEnrollmentV2
from saxo_provider import configured_client


def _prepare_pending_retry_v2(
    enrollment: StrategyEnrollmentV2,
    *,
    observations: tuple[PositionObservationV2, ...],
) -> tuple[bool, bool]:
    """Return (matching request existed, terminal request was actually re-armed).

    The v1 normalized runtime persisted the same idempotent request on every pending
    cycle and interpreted a non-null request id as a fresh retry. ON CONFLICT made that
    a no-op once the request already existed. Reuse the hardened MACD retry contract so
    only an exact BLOCKED/REJECTED request for the still-current intent is moved back to
    PENDING; SUBMITTING/ORDER_ACCEPTED/UNCERTAIN work is never touched.
    """
    state = load_fast_live_state_v2(enrollment)
    if state is None or state.pending_target_direction is None:
        return False, False

    observed = _exact_product_observation(enrollment, observations)
    observed_direction = _observed_direction(observed)
    if observed_direction == state.pending_target_direction:
        return False, False

    existed = _matching_intent_request_exists_v1(
        enrollment,
        state,
        observed_direction=observed_direction,
    )
    rearmed = _rearm_retryable_terminal_request_v1(
        enrollment,
        state,
        observed_direction=observed_direction,
    )
    return bool(existed), bool(rearmed)


def run_macd_normalized_live_once_v2(
    enrollment: StrategyEnrollmentV2,
    *,
    db_path: str = "pricegauger.db",
    now: datetime | None = None,
    observations: tuple[PositionObservationV2, ...] | None = None,
) -> FastLiveCycleV2:
    """Normalized MACD LIVE facade with truthful durable pending-request retries."""
    if observations is None:
        client = configured_client()
        if client is None:
            raise RuntimeError("Saxo client is not configured")
        observations = _position_observations_v2(client)

    existed_before, rearmed = _prepare_pending_retry_v2(
        enrollment,
        observations=observations,
    )
    cycle = _run_macd_normalized_live_once_v1(
        enrollment,
        db_path=db_path,
        now=now,
        observations=observations,
    )

    if cycle.reason not in {
        "PENDING_TRANSITION_RETRY_READY",
        "PENDING_TRANSITION_CONTINUED",
    }:
        return cycle

    # If no request existed before this cycle, v1 really did create it. If an exact
    # terminal request existed, `rearmed` records the real PENDING transition. Any
    # other existing request is merely continuing in the downstream execution path.
    retry_ready = bool(rearmed or (cycle.request_created and not existed_before))
    return replace(
        cycle,
        request_created=retry_ready,
        reason=(
            "PENDING_TRANSITION_RETRY_READY"
            if retry_ready
            else "PENDING_TRANSITION_CONTINUED"
        ),
    )


# Keep the dispatcher import surface compact and backwards-readable.
run_macd_normalized_live_once_v1 = run_macd_normalized_live_once_v2


__all__ = [
    "MACD_NORMALIZED_LIVE_STRATEGIES_V1",
    "_prepare_pending_retry_v2",
    "run_macd_normalized_live_once_v1",
    "run_macd_normalized_live_once_v2",
]
