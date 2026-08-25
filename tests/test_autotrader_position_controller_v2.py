from datetime import datetime, timezone

import pytest

from autotrader_position_controller_v2 import (
    ACTION_ADD,
    ACTION_CLOSE,
    ACTION_HOLD,
    ACTION_OPEN,
    ACTION_REDUCE,
    DIRECTION_FLAT,
    DIRECTION_LONG,
    DIRECTION_SHORT,
    PositionStateV2,
    PositionTargetV2,
    decide_position_action_v2,
)


def target(direction: str, fraction: float, *, rationale: str = "technical policy") -> PositionTargetV2:
    return PositionTargetV2(
        market_id=1,
        market_name="Gold",
        direction=direction,
        target_fraction=fraction,
        budget_amount=10_000.0,
        budget_currency="NOK",
        strategy_key="test-policy-v1",
        signal_at=datetime(2026, 8, 25, 20, 0, tzinfo=timezone.utc),
        rationale=rationale,
        source_fingerprint="technical-snapshot-1",
    )


def test_target_budget_amount_is_explicit_fraction_of_disposable_budget():
    assert target(DIRECTION_LONG, 0.35).target_budget_amount == 3500.0


def test_flat_target_requires_zero_fraction():
    with pytest.raises(ValueError):
        target(DIRECTION_FLAT, 0.1)


def test_open_from_flat_uses_target_fraction():
    decision = decide_position_action_v2(PositionStateV2(), target(DIRECTION_LONG, 0.4))
    assert decision.action == ACTION_OPEN
    assert decision.desired_direction == DIRECTION_LONG
    assert decision.delta_fraction == pytest.approx(0.4)


def test_add_and_reduce_are_incremental_not_all_or_nothing():
    add = decide_position_action_v2(
        PositionStateV2(direction=DIRECTION_LONG, deployed_fraction=0.25),
        target(DIRECTION_LONG, 0.70),
    )
    reduce = decide_position_action_v2(
        PositionStateV2(direction=DIRECTION_LONG, deployed_fraction=0.80),
        target(DIRECTION_LONG, 0.45),
    )
    assert add.action == ACTION_ADD
    assert add.delta_fraction == pytest.approx(0.45)
    assert reduce.action == ACTION_REDUCE
    assert reduce.delta_fraction == pytest.approx(-0.35)


def test_small_rebalance_is_hold_to_avoid_churn():
    decision = decide_position_action_v2(
        PositionStateV2(direction=DIRECTION_SHORT, deployed_fraction=0.50),
        target(DIRECTION_SHORT, 0.53),
        rebalance_threshold=0.05,
    )
    assert decision.action == ACTION_HOLD
    assert decision.delta_fraction == 0.0


def test_flat_target_closes_existing_position():
    decision = decide_position_action_v2(
        PositionStateV2(direction=DIRECTION_LONG, deployed_fraction=0.65),
        target(DIRECTION_FLAT, 0.0),
    )
    assert decision.action == ACTION_CLOSE
    assert decision.delta_fraction == pytest.approx(-0.65)


def test_direction_reversal_must_close_first_and_never_reverse_in_one_action():
    decision = decide_position_action_v2(
        PositionStateV2(direction=DIRECTION_LONG, deployed_fraction=0.60),
        target(DIRECTION_SHORT, 0.75),
    )
    assert decision.action == ACTION_CLOSE
    assert decision.prior_direction == DIRECTION_LONG
    assert decision.desired_direction == DIRECTION_SHORT
    assert decision.delta_fraction == pytest.approx(-0.60)


def test_once_confirmed_flat_next_cycle_can_open_opposite_direction():
    decision = decide_position_action_v2(
        PositionStateV2(direction=DIRECTION_FLAT, deployed_fraction=0.0),
        target(DIRECTION_SHORT, 0.75),
    )
    assert decision.action == ACTION_OPEN
    assert decision.desired_direction == DIRECTION_SHORT
    assert decision.delta_fraction == pytest.approx(0.75)


def test_invalid_fraction_is_rejected():
    with pytest.raises(ValueError):
        target(DIRECTION_LONG, 1.01)
    with pytest.raises(ValueError):
        PositionStateV2(direction=DIRECTION_LONG, deployed_fraction=-0.1)
