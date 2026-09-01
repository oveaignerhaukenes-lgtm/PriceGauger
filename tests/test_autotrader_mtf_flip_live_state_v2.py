from __future__ import annotations

from datetime import datetime, timezone

from autotrader_mtf_flip_live_runtime_v2 import (
    MtfFlipLiveStateV2,
    MtfFlipPendingV2,
    _pending_decision,
    _reconcile_state_to_observed_v2,
    _request_action,
)
from autotrader_mtf_flip_policy_v2 import (
    ACTION_FLIP_SHORT,
    DIRECTION_FLAT,
    DIRECTION_LONG,
    DIRECTION_SHORT,
    STATE_CONFIRMED_30M_LONG,
    STATE_CONFIRMED_30M_SHORT,
    STATE_FLAT,
)


SIGNAL_AT = datetime(2026, 9, 1, 10, 30, tzinfo=timezone.utc)


def pending_short() -> MtfFlipPendingV2:
    return MtfFlipPendingV2(
        event_id="11111111-1111-1111-1111-111111111111",
        event_type="FLIP_30M_TO_SHORT",
        signal_at=SIGNAL_AT,
        signal="CROSS_DOWN",
        target_direction=DIRECTION_SHORT,
        previous_macd=1.0,
        previous_signal=0.5,
        current_macd=-0.2,
        current_signal=0.1,
    )


def test_request_planner_never_encodes_one_order_reverse() -> None:
    assert _request_action(DIRECTION_LONG, DIRECTION_SHORT) == "CLOSE"
    assert _request_action(DIRECTION_SHORT, DIRECTION_LONG) == "CLOSE"
    assert _request_action(DIRECTION_FLAT, DIRECTION_SHORT) == "OPEN"
    assert _request_action(DIRECTION_FLAT, DIRECTION_LONG) == "OPEN"
    assert _request_action(DIRECTION_LONG, DIRECTION_LONG) is None
    assert _request_action(DIRECTION_SHORT, DIRECTION_SHORT) is None
    assert _request_action(DIRECTION_FLAT, DIRECTION_FLAT) is None


def test_pending_reversal_survives_confirmed_flat_until_target_is_observed() -> None:
    pending = pending_short()
    state = MtfFlipLiveStateV2(
        pilot_key="pilot-1",
        state=STATE_FLAT,
        pending=pending,
    )

    flat = _reconcile_state_to_observed_v2(state, DIRECTION_FLAT)
    assert flat.state == STATE_FLAT
    assert flat.pending == pending

    target = _reconcile_state_to_observed_v2(flat, DIRECTION_SHORT)
    assert target.state == STATE_CONFIRMED_30M_SHORT
    assert target.pending is None


def test_pending_reversal_does_not_clear_while_source_side_is_still_observed() -> None:
    pending = pending_short()
    state = MtfFlipLiveStateV2(
        pilot_key="pilot-1",
        state=STATE_FLAT,
        pending=pending,
    )
    still_long = _reconcile_state_to_observed_v2(state, DIRECTION_LONG)
    assert still_long.state == STATE_FLAT
    assert still_long.pending == pending


def test_external_exposure_change_without_pending_is_adopted_without_replay() -> None:
    state = MtfFlipLiveStateV2(pilot_key="pilot-1", state=STATE_FLAT)
    adopted_long = _reconcile_state_to_observed_v2(state, DIRECTION_LONG)
    assert adopted_long.state == STATE_CONFIRMED_30M_LONG
    assert adopted_long.pending is None

    adopted_short = _reconcile_state_to_observed_v2(state, DIRECTION_SHORT)
    assert adopted_short.state == STATE_CONFIRMED_30M_SHORT
    assert adopted_short.pending is None


def test_pending_decision_preserves_original_30m_target_identity() -> None:
    pending = pending_short()
    decision = _pending_decision(pending)
    assert decision.event_type == pending.event_type
    assert decision.action == ACTION_FLIP_SHORT
    assert decision.desired_direction == DIRECTION_SHORT
    assert decision.carry_reversal is True
    assert decision.desired_state == STATE_FLAT
