from datetime import datetime, timedelta, timezone

from autotrader_automanage_runtime_v2 import (
    AutoManageRuntimeStateV2,
    MACD_LONG_FLAT_STRATEGY_V2,
    plan_automanage_step_v2,
)
from autotrader_macd_dry_run_v2 import MacdObservationV2
from autotrader_macd_flip_policy_v2 import MACD_FLIP_STRATEGY_V2
from autotrader_position_controller_v2 import ACTION_CLOSE, ACTION_OPEN, DIRECTION_LONG, DIRECTION_SHORT
from autotrader_risk_control_v2 import PositionObservationV2
from autotrader_strategy_enrollment_v2 import EXECUTION_MODE_LIVE, StrategyEnrollmentV2


T0 = datetime(2026, 8, 29, 0, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(minutes=30)
T2 = T1 + timedelta(minutes=30)


def enrollment(strategy_key: str) -> StrategyEnrollmentV2:
    return StrategyEnrollmentV2(
        pilot_key=f"pilot-{strategy_key}",
        strategy_key=strategy_key,
        execution_mode=EXECUTION_MODE_LIVE,
        account_id="ACC-1",
        anchor_net_position_id="NET-1",
        uic=4912,
        asset_type="CfdOnIndex",
        market_id=7,
        instrument_id=11,
        market_name="Australia Tech",
        enabled=True,
        live_open_armed=False,
    )


def macd(at, value, signal):
    return MacdObservationV2(bar_time=at, macd=value, signal=signal)


def live_long() -> PositionObservationV2:
    return PositionObservationV2(
        account_id="ACC-1",
        net_position_id="NET-1",
        uic=4912,
        asset_type="CfdOnIndex",
        direction="Buy",
        amount=0.01,
        average_open_price=100.0,
        current_price=101.0,
        pnl_pct=1.0,
        price_delay_minutes=0,
        can_be_closed=True,
        calculation_reliability="Ok",
        is_market_open=True,
        non_tradable_reason="None",
    )


def test_bootstrap_adopts_live_position_without_replaying_cross():
    result = plan_automanage_step_v2(
        enrollment=enrollment(MACD_LONG_FLAT_STRATEGY_V2),
        state=AutoManageRuntimeStateV2(),
        observed_position=live_long(),
        previous=macd(T0, 0.3, 0.1),
        current=macd(T1, -0.2, -0.1),
        budget_amount=500.0,
        budget_currency="NOK",
    )
    assert result.outcome_reason == "BOOTSTRAP_NO_REPLAY"
    assert result.intent is None
    assert result.decision is None


def test_long_flat_bearish_cross_closes_to_cash_and_never_shortens():
    result = plan_automanage_step_v2(
        enrollment=enrollment(MACD_LONG_FLAT_STRATEGY_V2),
        state=AutoManageRuntimeStateV2(last_evaluated_bar_time=T0),
        observed_position=live_long(),
        previous=macd(T0, 0.3, 0.1),
        current=macd(T1, -0.2, -0.1),
        budget_amount=500.0,
        budget_currency="NOK",
    )
    assert result.intent is not None
    assert result.intent.target_direction == "FLAT"
    assert result.decision is not None
    assert result.decision.action == ACTION_CLOSE
    assert result.decision.desired_direction == "FLAT"
    assert result.next_state.pending_intent is None


def test_flip_bearish_cross_closes_long_then_carries_short_intent():
    result = plan_automanage_step_v2(
        enrollment=enrollment(MACD_FLIP_STRATEGY_V2),
        state=AutoManageRuntimeStateV2(last_evaluated_bar_time=T0),
        observed_position=live_long(),
        previous=macd(T0, 0.3, 0.1),
        current=macd(T1, -0.2, -0.1),
        budget_amount=500.0,
        budget_currency="NOK",
    )
    assert result.intent is not None
    assert result.intent.target_direction == DIRECTION_SHORT
    assert result.decision is not None and result.decision.action == ACTION_CLOSE
    assert result.next_state.pending_intent == result.intent


def test_pending_flip_opens_only_after_observed_flat_and_rebudgets_profit():
    first = plan_automanage_step_v2(
        enrollment=enrollment(MACD_FLIP_STRATEGY_V2),
        state=AutoManageRuntimeStateV2(last_evaluated_bar_time=T0),
        observed_position=live_long(),
        previous=macd(T0, 0.3, 0.1),
        current=macd(T1, -0.2, -0.1),
        budget_amount=500.0,
        budget_currency="NOK",
    )
    second = plan_automanage_step_v2(
        enrollment=enrollment(MACD_FLIP_STRATEGY_V2),
        state=first.next_state,
        observed_position=None,
        previous=macd(T1, -0.3, -0.1),
        current=macd(T2, -0.4, -0.2),
        budget_amount=1500.0,
        budget_currency="NOK",
    )
    assert second.intent is not None
    assert second.intent.budget_amount == 1500.0
    assert second.decision is not None
    assert second.decision.action == ACTION_OPEN
    assert second.decision.desired_direction == DIRECTION_SHORT


def test_long_flat_fresh_bullish_cross_opens_long_from_flat():
    result = plan_automanage_step_v2(
        enrollment=enrollment(MACD_LONG_FLAT_STRATEGY_V2),
        state=AutoManageRuntimeStateV2(last_evaluated_bar_time=T1),
        observed_position=None,
        previous=macd(T1, -0.3, -0.1),
        current=macd(T2, 0.2, 0.1),
        budget_amount=620.0,
        budget_currency="NOK",
    )
    assert result.intent is not None and result.intent.target_direction == DIRECTION_LONG
    assert result.decision is not None
    assert result.decision.action == ACTION_OPEN
    assert result.intent.budget_amount == 620.0


def test_exhausted_equity_blocks_open_but_not_close():
    open_result = plan_automanage_step_v2(
        enrollment=enrollment(MACD_LONG_FLAT_STRATEGY_V2),
        state=AutoManageRuntimeStateV2(last_evaluated_bar_time=T1),
        observed_position=None,
        previous=macd(T1, -0.3, -0.1),
        current=macd(T2, 0.2, 0.1),
        budget_amount=0.0,
        budget_currency="NOK",
    )
    assert open_result.decision is not None and open_result.decision.action == ACTION_OPEN
    assert open_result.outcome_reason == "ENTRY_BLOCKED_EQUITY_EXHAUSTED"

    close_result = plan_automanage_step_v2(
        enrollment=enrollment(MACD_LONG_FLAT_STRATEGY_V2),
        state=AutoManageRuntimeStateV2(last_evaluated_bar_time=T0),
        observed_position=live_long(),
        previous=macd(T0, 0.3, 0.1),
        current=macd(T1, -0.2, -0.1),
        budget_amount=0.0,
        budget_currency="NOK",
    )
    assert close_result.decision is not None and close_result.decision.action == ACTION_CLOSE
