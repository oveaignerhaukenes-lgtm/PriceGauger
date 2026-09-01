from __future__ import annotations

from datetime import datetime, timedelta, timezone

from autotrader_mtf_entry_shadow_v2 import (
    CONTEXT_BULLISH,
    CONTEXT_RECOVERING,
    ENTRY_TIMEFRAME_MINUTES,
    MtfObservationV2,
    REGIME_TIMEFRAME_MINUTES,
    VALIDATION_TIMEFRAME_MINUTES,
)
from autotrader_mtf_flip_policy_v2 import (
    ACTION_CLOSE_FLAT,
    ACTION_CONFIRMATION,
    ACTION_FLIP_LONG,
    ACTION_FLIP_SHORT,
    ACTION_OPEN_LONG,
    ACTION_OPEN_SHORT,
    DIRECTION_LONG,
    DIRECTION_SHORT,
    EVENT_CONFIRM_10M_LONG,
    EVENT_CONFIRM_10M_SHORT,
    EVENT_CONFIRM_30M_LONG,
    EVENT_CONFIRM_30M_SHORT,
    EVENT_ENTRY_5M_LONG,
    EVENT_ENTRY_5M_SHORT,
    EVENT_FLIP_30M_TO_LONG,
    EVENT_FLIP_30M_TO_SHORT,
    EVENT_REJECT_10M_LONG,
    EVENT_REJECT_10M_SHORT,
    EVENT_REJECT_5M_LONG,
    EVENT_REJECT_5M_SHORT,
    STATE_CONFIRMED_30M_LONG,
    STATE_CONFIRMED_30M_SHORT,
    STATE_FLAT,
    STATE_PROVISIONAL_LONG,
    STATE_PROVISIONAL_SHORT,
    STATE_VALIDATED_10M_LONG,
    STATE_VALIDATED_10M_SHORT,
    mtf_flip_decision_v2,
)
from autotrader_mtf_short_policy_v2 import CONTEXT_BEARISH, CONTEXT_DETERIORATING


BASE = datetime(2026, 9, 1, tzinfo=timezone.utc)


def obs(*, minutes: int, index: int, spread: float, close: float = 100.0) -> MtfObservationV2:
    bar = BASE + timedelta(minutes=minutes * index)
    return MtfObservationV2(
        bar_time=bar,
        closed_at=bar + timedelta(minutes=minutes),
        timeframe_minutes=minutes,
        close=close,
        macd=spread,
        signal=0.0,
    )


def decide(*, state: str, minutes: int, previous: MtfObservationV2, current: MtfObservationV2,
           long_context: str = CONTEXT_BULLISH, short_context: str = CONTEXT_BEARISH):
    return mtf_flip_decision_v2(
        state=state,
        timeframe_minutes=minutes,
        previous=previous,
        current=current,
        long_context_30m=long_context,
        short_context_30m=short_context,
    )


def test_flat_5m_can_enter_either_direction_from_matching_30m_context() -> None:
    long_entry = decide(
        state=STATE_FLAT,
        minutes=ENTRY_TIMEFRAME_MINUTES,
        previous=obs(minutes=5, index=0, spread=-0.2),
        current=obs(minutes=5, index=1, spread=0.2),
        long_context=CONTEXT_RECOVERING,
        short_context=CONTEXT_BEARISH,
    )
    assert long_entry is not None
    assert long_entry.event_type == EVENT_ENTRY_5M_LONG
    assert long_entry.action == ACTION_OPEN_LONG
    assert long_entry.desired_direction == DIRECTION_LONG
    assert long_entry.desired_state == STATE_PROVISIONAL_LONG
    assert long_entry.carry_reversal is False

    short_entry = decide(
        state=STATE_FLAT,
        minutes=ENTRY_TIMEFRAME_MINUTES,
        previous=obs(minutes=5, index=0, spread=0.2),
        current=obs(minutes=5, index=1, spread=-0.2),
        long_context=CONTEXT_BULLISH,
        short_context=CONTEXT_DETERIORATING,
    )
    assert short_entry is not None
    assert short_entry.event_type == EVENT_ENTRY_5M_SHORT
    assert short_entry.action == ACTION_OPEN_SHORT
    assert short_entry.desired_direction == DIRECTION_SHORT
    assert short_entry.desired_state == STATE_PROVISIONAL_SHORT
    assert short_entry.carry_reversal is False


def test_fast_clock_rejections_flatten_only_and_never_flip() -> None:
    reject_long_5m = decide(
        state=STATE_PROVISIONAL_LONG,
        minutes=ENTRY_TIMEFRAME_MINUTES,
        previous=obs(minutes=5, index=1, spread=0.2),
        current=obs(minutes=5, index=2, spread=-0.1),
    )
    assert reject_long_5m is not None
    assert reject_long_5m.event_type == EVENT_REJECT_5M_LONG
    assert reject_long_5m.action == ACTION_CLOSE_FLAT
    assert reject_long_5m.desired_state == STATE_FLAT
    assert reject_long_5m.carry_reversal is False

    reject_short_5m = decide(
        state=STATE_PROVISIONAL_SHORT,
        minutes=ENTRY_TIMEFRAME_MINUTES,
        previous=obs(minutes=5, index=1, spread=-0.2),
        current=obs(minutes=5, index=2, spread=0.1),
    )
    assert reject_short_5m is not None
    assert reject_short_5m.event_type == EVENT_REJECT_5M_SHORT
    assert reject_short_5m.action == ACTION_CLOSE_FLAT
    assert reject_short_5m.carry_reversal is False

    reject_long_10m = decide(
        state=STATE_VALIDATED_10M_LONG,
        minutes=VALIDATION_TIMEFRAME_MINUTES,
        previous=obs(minutes=10, index=1, spread=0.3),
        current=obs(minutes=10, index=2, spread=-0.1),
    )
    assert reject_long_10m is not None
    assert reject_long_10m.event_type == EVENT_REJECT_10M_LONG
    assert reject_long_10m.action == ACTION_CLOSE_FLAT
    assert reject_long_10m.carry_reversal is False

    reject_short_10m = decide(
        state=STATE_VALIDATED_10M_SHORT,
        minutes=VALIDATION_TIMEFRAME_MINUTES,
        previous=obs(minutes=10, index=1, spread=-0.3),
        current=obs(minutes=10, index=2, spread=0.1),
    )
    assert reject_short_10m is not None
    assert reject_short_10m.event_type == EVENT_REJECT_10M_SHORT
    assert reject_short_10m.action == ACTION_CLOSE_FLAT
    assert reject_short_10m.carry_reversal is False


def test_10m_and_30m_confirmation_are_symmetric() -> None:
    long_10 = decide(
        state=STATE_PROVISIONAL_LONG,
        minutes=VALIDATION_TIMEFRAME_MINUTES,
        previous=obs(minutes=10, index=0, spread=-0.1),
        current=obs(minutes=10, index=1, spread=0.2),
    )
    assert long_10 is not None
    assert long_10.event_type == EVENT_CONFIRM_10M_LONG
    assert long_10.action == ACTION_CONFIRMATION
    assert long_10.desired_state == STATE_VALIDATED_10M_LONG

    short_10 = decide(
        state=STATE_PROVISIONAL_SHORT,
        minutes=VALIDATION_TIMEFRAME_MINUTES,
        previous=obs(minutes=10, index=0, spread=0.1),
        current=obs(minutes=10, index=1, spread=-0.2),
    )
    assert short_10 is not None
    assert short_10.event_type == EVENT_CONFIRM_10M_SHORT
    assert short_10.action == ACTION_CONFIRMATION
    assert short_10.desired_state == STATE_VALIDATED_10M_SHORT

    long_30 = decide(
        state=STATE_VALIDATED_10M_LONG,
        minutes=REGIME_TIMEFRAME_MINUTES,
        previous=obs(minutes=30, index=0, spread=-0.2),
        current=obs(minutes=30, index=1, spread=0.2),
    )
    assert long_30 is not None
    assert long_30.event_type == EVENT_CONFIRM_30M_LONG
    assert long_30.desired_state == STATE_CONFIRMED_30M_LONG

    short_30 = decide(
        state=STATE_VALIDATED_10M_SHORT,
        minutes=REGIME_TIMEFRAME_MINUTES,
        previous=obs(minutes=30, index=0, spread=0.2),
        current=obs(minutes=30, index=1, spread=-0.2),
    )
    assert short_30 is not None
    assert short_30.event_type == EVENT_CONFIRM_30M_SHORT
    assert short_30.desired_state == STATE_CONFIRMED_30M_SHORT


def test_opposite_closed_30m_cross_is_the_only_carried_flip_signal() -> None:
    to_short = decide(
        state=STATE_CONFIRMED_30M_LONG,
        minutes=REGIME_TIMEFRAME_MINUTES,
        previous=obs(minutes=30, index=0, spread=0.2),
        current=obs(minutes=30, index=1, spread=-0.2),
        short_context=CONTEXT_BEARISH,
    )
    assert to_short is not None
    assert to_short.event_type == EVENT_FLIP_30M_TO_SHORT
    assert to_short.action == ACTION_FLIP_SHORT
    assert to_short.desired_direction == DIRECTION_SHORT
    assert to_short.desired_state == STATE_FLAT
    assert to_short.carry_reversal is True

    to_long = decide(
        state=STATE_CONFIRMED_30M_SHORT,
        minutes=REGIME_TIMEFRAME_MINUTES,
        previous=obs(minutes=30, index=0, spread=-0.2),
        current=obs(minutes=30, index=1, spread=0.2),
        long_context=CONTEXT_BULLISH,
    )
    assert to_long is not None
    assert to_long.event_type == EVENT_FLIP_30M_TO_LONG
    assert to_long.action == ACTION_FLIP_LONG
    assert to_long.desired_direction == DIRECTION_LONG
    assert to_long.desired_state == STATE_FLAT
    assert to_long.carry_reversal is True


def test_flat_entry_requires_matching_directional_context() -> None:
    blocked_long = decide(
        state=STATE_FLAT,
        minutes=ENTRY_TIMEFRAME_MINUTES,
        previous=obs(minutes=5, index=0, spread=-0.2),
        current=obs(minutes=5, index=1, spread=0.2),
        long_context="BEARISH",
    )
    assert blocked_long is None

    blocked_short = decide(
        state=STATE_FLAT,
        minutes=ENTRY_TIMEFRAME_MINUTES,
        previous=obs(minutes=5, index=0, spread=0.2),
        current=obs(minutes=5, index=1, spread=-0.2),
        short_context="BULLISH",
    )
    assert blocked_short is None
