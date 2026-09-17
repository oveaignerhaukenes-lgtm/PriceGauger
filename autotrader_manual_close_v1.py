from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from autotrader_fast_live_runtime_v2 import (
    DIRECTION_FLAT,
    FastLiveStateV2,
    _observed_direction,
    _persist_intent_and_request_v2,
)
from autotrader_managed_positions_v1 import is_position_managed_v1
from autotrader_manual_entry_adoption_v2 import adopt_user_confirmed_position_v2
from autotrader_pilot_equity_v2 import load_pilot_equity_v2
from autotrader_risk_control_v2 import PositionObservationV2
from autotrader_strategy_enrollment_v2 import EXECUTION_MODE_LIVE, StrategyEnrollmentV2
from autotrader_strategy_switch_v2 import _pg_execution_inflight_v2, _quiesce_source_authority_v2


@dataclass(frozen=True, slots=True)
class ManualCloseResultV1:
    pilot_key: str
    observed_direction: str
    request_created: bool
    already_flat: bool


def request_manual_close_v1(
    enrollment: StrategyEnrollmentV2,
    *,
    observation: PositionObservationV2 | None,
    now: datetime | None = None,
) -> ManualCloseResultV1:
    """Request FLAT through the existing durable execution-request lifecycle.

    This function has no broker POST authority.  It creates the same CLOSE request
    consumed by the hardened close runtime, so prechecks, exact product identity and
    reconciliation remain authoritative downstream.
    """
    if enrollment.execution_mode != EXECUTION_MODE_LIVE or not enrollment.enabled:
        raise ValueError("manual close requires an active LIVE AutoManager pilot")
    if _pg_execution_inflight_v2(enrollment):
        raise ValueError("vent til pågående PriceGauger/Saxo-ordre er ferdig")

    observed_direction = _observed_direction(observation)
    if observed_direction == DIRECTION_FLAT:
        return ManualCloseResultV1(
            enrollment.pilot_key,
            observed_direction,
            False,
            True,
        )

    if observation is not None and not is_position_managed_v1(observation):
        adopt_user_confirmed_position_v2(enrollment, observation)

    _quiesce_source_authority_v2(enrollment)
    requested_at = now or datetime.now(timezone.utc)
    if requested_at.tzinfo is None:
        requested_at = requested_at.replace(tzinfo=timezone.utc)
    else:
        requested_at = requested_at.astimezone(timezone.utc)

    state = FastLiveStateV2(
        pilot_key=enrollment.pilot_key,
        strategy_key=enrollment.strategy_key,
        desired_direction=DIRECTION_FLAT,
        last_action_at=requested_at,
        pending_target_direction=DIRECTION_FLAT,
        intent_event_id=str(uuid4()),
        intent_signal_at=requested_at,
        intent_signal="USER_CLOSE_POSITION",
    )
    equity = load_pilot_equity_v2(pilot_key=enrollment.pilot_key)
    created = _persist_intent_and_request_v2(
        enrollment=enrollment,
        state=state,
        observed=observation,
        observed_direction=observed_direction,
        budget_amount=equity.entry_budget,
        budget_currency=equity.currency,
        supersede_prior=True,
    )
    return ManualCloseResultV1(
        enrollment.pilot_key,
        observed_direction,
        bool(created),
        False,
    )


__all__ = ["ManualCloseResultV1", "request_manual_close_v1"]
