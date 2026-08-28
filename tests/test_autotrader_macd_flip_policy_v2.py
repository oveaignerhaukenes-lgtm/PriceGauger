from datetime import datetime, timedelta, timezone

import pytest

from autotrader_macd_dry_run_v2 import SIGNAL_DOWN, SIGNAL_UP, MacdObservationV2
from autotrader_macd_flip_policy_v2 import (
    MACD_FLIP_STRATEGY_V2,
    macd_flip_intent_from_pair_v2,
    plan_macd_flip_action_v2,
    reentry_intent_is_fresh_v2,
)
from autotrader_position_controller_v2 import (
    ACTION_CLOSE,
    ACTION_HOLD,
    ACTION_OPEN,
    DIRECTION_FLAT,
    DIRECTION_LONG,
    DIRECTION_SHORT,
    PositionStateV2,
)


T0 = datetime(2026, 8, 28, 20, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(minutes=30)


def obs(at, macd, signal):
    return MacdObservationV2(bar_time=at, macd=macd, signal=signal)


def intent(previous, current):
    result = macd_flip_intent_from_pair_v2(
        market_id=7,
        market_name="Test Australia Tech",
        previous=previous,
        current=current,
        target_fraction=1.0,
        budget_amount=340.0,
        budget_currency="NOK",
    )
    assert result is not None
    return result


def test_cross_up_creates_long_intent_from_closed_observation_pair():
    item = intent(obs(T0, -0.3, -0.1), obs(T1, 0.2, 0.1))
    assert item.signal == SIGNAL_UP
    assert item.target_direction == DIRECTION_LONG
    assert item.strategy_key == MACD_FLIP_STRATEGY_V2
    assert item.signal_at == T1
    assert item.to_position_target().target_budget_amount == pytest.approx(340.0)


def test_cross_down_creates_short_intent():
    item = intent(obs(T0, 0.3, 0.1), obs(T1, -0.2, -0.1))
    assert item.signal == SIGNAL_DOWN
    assert item.target_direction == DIRECTION_SHORT


def test_no_cross_creates_no_intent():
    item = macd_flip_intent_from_pair_v2(
        market_id=7,
        market_name="Test Australia Tech",
        previous=obs(T0, 0.3, 0.1),
        current=obs(T1, 0.4, 0.2),
        target_fraction=1.0,
        budget_amount=340.0,
    )
    assert item is None


def test_reversal_is_close_then_confirmed_flat_then_open_opposite():
    short_intent = intent(obs(T0, 0.3, 0.1), obs(T1, -0.2, -0.1))

    close = plan_macd_flip_action_v2(
        current=PositionStateV2(direction=DIRECTION_LONG, deployed_fraction=1.0),
        intent=short_intent,
    )
    assert close.action == ACTION_CLOSE
    assert close.prior_direction == DIRECTION_LONG
    assert close.desired_direction == DIRECTION_SHORT

    reopen = plan_macd_flip_action_v2(
        current=PositionStateV2(direction=DIRECTION_FLAT, deployed_fraction=0.0),
        intent=short_intent,
    )
    assert reopen.action == ACTION_OPEN
    assert reopen.prior_direction == DIRECTION_FLAT
    assert reopen.desired_direction == DIRECTION_SHORT


def test_same_side_signal_does_not_pyramid_or_rebalance_existing_position():
    long_intent = intent(obs(T0, -0.3, -0.1), obs(T1, 0.2, 0.1))
    hold = plan_macd_flip_action_v2(
        current=PositionStateV2(direction=DIRECTION_LONG, deployed_fraction=0.42),
        intent=long_intent,
    )
    assert hold.action == ACTION_HOLD
    assert hold.delta_fraction == 0.0


def test_hard_stop_reentry_requires_cross_after_becoming_flat():
    long_intent = intent(obs(T0, -0.3, -0.1), obs(T1, 0.2, 0.1))
    assert not reentry_intent_is_fresh_v2(intent=long_intent, flat_since=T1)
    assert not reentry_intent_is_fresh_v2(intent=long_intent, flat_since=T1 + timedelta(seconds=1))
    assert reentry_intent_is_fresh_v2(intent=long_intent, flat_since=T0)


def test_invalid_naive_flat_since_is_rejected():
    long_intent = intent(obs(T0, -0.3, -0.1), obs(T1, 0.2, 0.1))
    with pytest.raises(ValueError):
        reentry_intent_is_fresh_v2(intent=long_intent, flat_since=datetime(2026, 8, 28, 20, 1))
