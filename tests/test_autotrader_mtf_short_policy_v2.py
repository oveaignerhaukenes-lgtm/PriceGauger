from __future__ import annotations

from datetime import datetime, timedelta, timezone

from autotrader_mtf_entry_shadow_v2 import (
    ACTION_CONFIRMATION,
    ACTION_WOULD_EXIT,
    ACTION_WOULD_EXIT_REARM,
    ENTRY_TIMEFRAME_MINUTES,
    MtfObservationV2,
    REGIME_TIMEFRAME_MINUTES,
    VALIDATION_TIMEFRAME_MINUTES,
)
from autotrader_mtf_short_policy_v2 import (
    ACTION_WOULD_SELL,
    CONTEXT_BEARISH,
    CONTEXT_BULLISH,
    CONTEXT_DETERIORATING,
    EVENT_CONFIRM_10M_SHORT,
    EVENT_CONFIRM_30M_SHORT,
    EVENT_ENTRY_5M_SHORT,
    EVENT_EXIT_30M_SHORT,
    EVENT_REJECT_10M_SHORT,
    EVENT_REJECT_5M_SHORT,
    STATE_CONFIRMED_30M_SHORT,
    STATE_FLAT,
    STATE_PROVISIONAL_SHORT,
    STATE_VALIDATED_10M_SHORT,
    short_decision_for_observation_v2,
    short_regime_context_30m_v2,
)


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


def test_short_context_allows_bearish_and_deteriorating_30m() -> None:
    assert short_regime_context_30m_v2(
        obs(minutes=30, index=0, spread=-1.0),
        obs(minutes=30, index=1, spread=-2.0),
    ) == CONTEXT_BEARISH
    assert short_regime_context_30m_v2(
        obs(minutes=30, index=0, spread=2.0),
        obs(minutes=30, index=1, spread=1.0),
    ) == CONTEXT_DETERIORATING
    assert short_regime_context_30m_v2(
        obs(minutes=30, index=0, spread=1.0),
        obs(minutes=30, index=1, spread=2.0),
    ) == CONTEXT_BULLISH


def test_5m_cross_down_enters_short_and_cross_up_rearms() -> None:
    entry = short_decision_for_observation_v2(
        state=STATE_FLAT,
        timeframe_minutes=ENTRY_TIMEFRAME_MINUTES,
        previous=obs(minutes=5, index=0, spread=0.2),
        current=obs(minutes=5, index=1, spread=-0.2),
        context_30m=CONTEXT_DETERIORATING,
    )
    assert entry is not None
    assert entry.event_type == EVENT_ENTRY_5M_SHORT
    assert entry.action == ACTION_WOULD_SELL
    assert entry.desired_state == STATE_PROVISIONAL_SHORT

    reject = short_decision_for_observation_v2(
        state=STATE_PROVISIONAL_SHORT,
        timeframe_minutes=ENTRY_TIMEFRAME_MINUTES,
        previous=obs(minutes=5, index=1, spread=-0.2),
        current=obs(minutes=5, index=2, spread=0.1),
        context_30m=CONTEXT_DETERIORATING,
    )
    assert reject is not None
    assert reject.event_type == EVENT_REJECT_5M_SHORT
    assert reject.action == ACTION_WOULD_EXIT_REARM
    assert reject.desired_state == STATE_FLAT


def test_10m_validates_short_then_can_reject_before_30m_confirmation() -> None:
    confirm = short_decision_for_observation_v2(
        state=STATE_PROVISIONAL_SHORT,
        timeframe_minutes=VALIDATION_TIMEFRAME_MINUTES,
        previous=obs(minutes=10, index=0, spread=0.1),
        current=obs(minutes=10, index=1, spread=-0.3),
        context_30m=CONTEXT_DETERIORATING,
    )
    assert confirm is not None
    assert confirm.event_type == EVENT_CONFIRM_10M_SHORT
    assert confirm.action == ACTION_CONFIRMATION
    assert confirm.desired_state == STATE_VALIDATED_10M_SHORT

    reject = short_decision_for_observation_v2(
        state=STATE_VALIDATED_10M_SHORT,
        timeframe_minutes=VALIDATION_TIMEFRAME_MINUTES,
        previous=obs(minutes=10, index=1, spread=-0.3),
        current=obs(minutes=10, index=2, spread=0.2),
        context_30m=CONTEXT_DETERIORATING,
    )
    assert reject is not None
    assert reject.event_type == EVENT_REJECT_10M_SHORT
    assert reject.action == ACTION_WOULD_EXIT_REARM


def test_30m_confirms_short_and_bullish_cross_exits() -> None:
    confirm = short_decision_for_observation_v2(
        state=STATE_VALIDATED_10M_SHORT,
        timeframe_minutes=REGIME_TIMEFRAME_MINUTES,
        previous=obs(minutes=30, index=0, spread=0.2),
        current=obs(minutes=30, index=1, spread=-0.2),
        context_30m=CONTEXT_BEARISH,
    )
    assert confirm is not None
    assert confirm.event_type == EVENT_CONFIRM_30M_SHORT
    assert confirm.action == ACTION_CONFIRMATION
    assert confirm.desired_state == STATE_CONFIRMED_30M_SHORT

    exit_decision = short_decision_for_observation_v2(
        state=STATE_CONFIRMED_30M_SHORT,
        timeframe_minutes=REGIME_TIMEFRAME_MINUTES,
        previous=obs(minutes=30, index=1, spread=-0.2),
        current=obs(minutes=30, index=2, spread=0.2),
        context_30m=CONTEXT_BULLISH,
    )
    assert exit_decision is not None
    assert exit_decision.event_type == EVENT_EXIT_30M_SHORT
    assert exit_decision.action == ACTION_WOULD_EXIT
    assert exit_decision.desired_state == STATE_FLAT


def test_short_entry_is_blocked_in_strengthening_bullish_context() -> None:
    decision = short_decision_for_observation_v2(
        state=STATE_FLAT,
        timeframe_minutes=ENTRY_TIMEFRAME_MINUTES,
        previous=obs(minutes=5, index=0, spread=0.2),
        current=obs(minutes=5, index=1, spread=-0.2),
        context_30m=CONTEXT_BULLISH,
    )
    assert decision is None
