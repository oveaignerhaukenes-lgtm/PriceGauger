from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from autotrader_macd_dry_run_v2 import MacdObservationV2
from autotrader_live_pilot_runtime_v2 import (
    LivePilotBindingV2,
    LivePilotPlanningStateV2,
    plan_live_pilot_step_v2,
    resolve_live_pilot_binding_v2,
)
from autotrader_macd_flip_policy_v2 import macd_flip_intent_from_pair_v2
from autotrader_position_controller_v2 import (
    ACTION_CLOSE,
    ACTION_HOLD,
    ACTION_OPEN,
    DIRECTION_FLAT,
    DIRECTION_LONG,
    DIRECTION_SHORT,
    PositionStateV2,
)


T0 = datetime(2026, 8, 29, 0, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(minutes=30)
T2 = T1 + timedelta(minutes=30)


def binding():
    return LivePilotBindingV2(
        account_id="ACC-1",
        anchor_net_position_id="NET-1",
        uic=12345,
        asset_type="CfdOnIndex",
        market_id=7,
        market_name="Australia Tech",
        instrument_id=11,
    )


def obs(at, macd, signal):
    return MacdObservationV2(bar_time=at, macd=macd, signal=signal)


def short_intent():
    item = macd_flip_intent_from_pair_v2(
        market_id=7,
        market_name="Australia Tech",
        previous=obs(T0, 0.3, 0.1),
        current=obs(T1, -0.2, -0.1),
        target_fraction=1.0,
        budget_amount=500.0,
    )
    assert item is not None
    return item


def test_bootstrap_consumes_latest_bar_without_replaying_cross():
    evaluation = plan_live_pilot_step_v2(
        binding=binding(),
        state=LivePilotPlanningStateV2(),
        observed_state=PositionStateV2(direction=DIRECTION_LONG, deployed_fraction=1.0),
        observed_net_position_id="NET-1",
        previous=obs(T0, 0.3, 0.1),
        current=obs(T1, -0.2, -0.1),
        budget_amount=500.0,
    )
    assert evaluation.outcome_reason == "BOOTSTRAP_NO_REPLAY"
    assert evaluation.intent is None
    assert evaluation.decision is None
    assert evaluation.next_state.last_evaluated_bar_time == T1
    assert not evaluation.next_state.reversal_pending


def test_fresh_opposite_cross_plans_close_and_persists_reversal_intent():
    evaluation = plan_live_pilot_step_v2(
        binding=binding(),
        state=LivePilotPlanningStateV2(last_evaluated_bar_time=T0),
        observed_state=PositionStateV2(direction=DIRECTION_LONG, deployed_fraction=1.0),
        observed_net_position_id="NET-1",
        previous=obs(T0, 0.3, 0.1),
        current=obs(T1, -0.2, -0.1),
        budget_amount=500.0,
    )
    assert evaluation.outcome_reason == "FRESH_MACD_CROSS"
    assert evaluation.intent is not None
    assert evaluation.intent.target_direction == DIRECTION_SHORT
    assert evaluation.decision is not None
    assert evaluation.decision.action == ACTION_CLOSE
    assert evaluation.next_state.reversal_pending
    assert evaluation.next_state.pending_intent == evaluation.intent


def test_pending_reversal_opens_only_after_observed_flat():
    pending = short_intent()
    evaluation = plan_live_pilot_step_v2(
        binding=binding(),
        state=LivePilotPlanningStateV2(
            last_evaluated_bar_time=T1,
            reversal_pending=True,
            pending_intent=pending,
        ),
        observed_state=PositionStateV2(direction=DIRECTION_FLAT, deployed_fraction=0.0),
        observed_net_position_id=None,
        previous=obs(T0, 0.3, 0.1),
        current=obs(T1, -0.2, -0.1),
        budget_amount=500.0,
    )
    assert evaluation.outcome_reason == "REVERSAL_PENDING"
    assert evaluation.intent == pending
    assert evaluation.decision is not None
    assert evaluation.decision.action == ACTION_OPEN
    assert evaluation.decision.desired_direction == DIRECTION_SHORT
    assert evaluation.next_state.reversal_pending


def test_pending_reversal_continues_across_new_bar_without_cross():
    pending = short_intent()
    evaluation = plan_live_pilot_step_v2(
        binding=binding(),
        state=LivePilotPlanningStateV2(
            last_evaluated_bar_time=T1,
            reversal_pending=True,
            pending_intent=pending,
        ),
        observed_state=PositionStateV2(direction=DIRECTION_LONG, deployed_fraction=1.0),
        observed_net_position_id="NET-1",
        previous=obs(T1, 0.3, 0.1),
        current=obs(T2, 0.4, 0.2),
        budget_amount=500.0,
    )
    assert evaluation.outcome_reason == "REVERSAL_PENDING"
    assert evaluation.intent == pending
    assert evaluation.decision is not None
    assert evaluation.decision.action == ACTION_CLOSE
    assert evaluation.next_state.last_evaluated_bar_time == T2
    assert evaluation.next_state.reversal_pending


def test_pending_reversal_settles_when_target_position_is_observed():
    pending = short_intent()
    evaluation = plan_live_pilot_step_v2(
        binding=binding(),
        state=LivePilotPlanningStateV2(
            last_evaluated_bar_time=T1,
            reversal_pending=True,
            pending_intent=pending,
        ),
        observed_state=PositionStateV2(direction=DIRECTION_SHORT, deployed_fraction=1.0),
        observed_net_position_id="NET-2",
        previous=obs(T0, 0.3, 0.1),
        current=obs(T1, -0.2, -0.1),
        budget_amount=500.0,
    )
    assert evaluation.outcome_reason == "REVERSAL_TARGET_OBSERVED"
    assert evaluation.decision is not None
    assert evaluation.decision.action == ACTION_HOLD
    assert not evaluation.next_state.reversal_pending
    assert evaluation.next_state.pending_intent is None


def test_flat_after_unrelated_stop_does_not_reopen_from_stale_signal():
    evaluation = plan_live_pilot_step_v2(
        binding=binding(),
        state=LivePilotPlanningStateV2(last_evaluated_bar_time=T1),
        observed_state=PositionStateV2(direction=DIRECTION_FLAT, deployed_fraction=0.0),
        observed_net_position_id=None,
        previous=obs(T0, 0.3, 0.1),
        current=obs(T1, -0.2, -0.1),
        budget_amount=500.0,
    )
    assert evaluation.outcome_reason == "NO_NEW_CROSS"
    assert evaluation.intent is None
    assert evaluation.decision is None
    assert not evaluation.next_state.reversal_pending


def test_exact_saxo_binding_requires_asset_type_match(monkeypatch):
    source = SimpleNamespace(
        market_id=7,
        market_name="Australia Tech",
        instrument_id=11,
        asset_type="CfdOnIndex",
    )
    monkeypatch.setattr(
        "autotrader_live_pilot_runtime_v2.resolve_instrument_source_v2",
        lambda **kwargs: source,
    )
    resolved = resolve_live_pilot_binding_v2(
        account_id="ACC-1",
        anchor_net_position_id="NET-1",
        uic=12345,
        asset_type="CfdOnIndex",
    )
    assert resolved.market_id == 7
    assert resolved.instrument_id == 11
    assert resolved.source_fingerprint.startswith("saxo|12345|CfdOnIndex|")


def test_fresh_cross_can_open_from_flat_but_only_on_new_bar():
    evaluation = plan_live_pilot_step_v2(
        binding=binding(),
        state=LivePilotPlanningStateV2(last_evaluated_bar_time=T1),
        observed_state=PositionStateV2(direction=DIRECTION_FLAT, deployed_fraction=0.0),
        observed_net_position_id=None,
        previous=obs(T1, -0.3, -0.1),
        current=obs(T2, 0.2, 0.1),
        budget_amount=500.0,
    )
    assert evaluation.intent is not None
    assert evaluation.intent.target_direction == DIRECTION_LONG
    assert evaluation.decision is not None
    assert evaluation.decision.action == ACTION_OPEN
