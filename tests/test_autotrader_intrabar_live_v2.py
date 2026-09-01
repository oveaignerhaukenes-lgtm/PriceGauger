from datetime import datetime, timedelta, timezone

from autotrader_automanage_runtime_v2 import AutoManageRuntimeStateV2, plan_automanage_step_v2
from autotrader_live_signal_clock_v2 import (
    SIGNAL_CLOCK_CLOSED_30M,
    SIGNAL_CLOCK_INTRABAR_30M_1M,
    automanage_signal_clock_v2,
    automanage_signal_pair_v2,
)
from autotrader_pnl_comparison_v2 import PAPER_BENCHMARK_STRATEGY_KEYS_V2
from autotrader_strategy_catalog_v2 import (
    INTRABAR_30M_LONG_FLAT_STRATEGY_V2,
    MACD_LONG_FLAT_STRATEGY_V2,
)
from autotrader_strategy_enrollment_v2 import (
    ENTRY_MODE_AUTO,
    EXECUTION_MODE_LIVE,
    StrategyEnrollmentV2,
)


def _flat_history_then_move() -> tuple[tuple[str, float], ...]:
    start = datetime(2026, 8, 31, 0, 0, tzinfo=timezone.utc)
    points: list[tuple[str, float]] = []
    for index in range(40):
        stamp = start + timedelta(minutes=index * 30 + 29)
        points.append((stamp.isoformat(), 100.0))
    forming = start + timedelta(minutes=40 * 30)
    points.append((forming.isoformat(), 100.0))
    points.append(((forming + timedelta(minutes=1)).isoformat(), 110.0))
    return tuple(points)


def _enrollment() -> StrategyEnrollmentV2:
    return StrategyEnrollmentV2(
        pilot_key="pilot-intrabar-live",
        strategy_key=INTRABAR_30M_LONG_FLAT_STRATEGY_V2,
        execution_mode=EXECUTION_MODE_LIVE,
        account_id="ACC-1",
        anchor_net_position_id="NET-1",
        uic=4912,
        asset_type="CfdOnIndex",
        market_id=7,
        instrument_id=11,
        market_name="US Tech 100 NAS · Saxo 4912",
        enabled=True,
        live_open_armed=True,
        entry_mode=ENTRY_MODE_AUTO,
    )


def test_intrabar_is_a_distinct_live_signal_clock():
    assert automanage_signal_clock_v2(MACD_LONG_FLAT_STRATEGY_V2) == SIGNAL_CLOCK_CLOSED_30M
    assert automanage_signal_clock_v2(INTRABAR_30M_LONG_FLAT_STRATEGY_V2) == SIGNAL_CLOCK_INTRABAR_30M_1M


def test_intrabar_live_pair_observes_cross_before_30m_close():
    previous, current = automanage_signal_pair_v2(
        strategy_key=INTRABAR_30M_LONG_FLAT_STRATEGY_V2,
        points=_flat_history_then_move(),
        market="US Tech 100 NAS · Saxo 4912",
    )
    assert current.bar_time - previous.bar_time == timedelta(minutes=1)
    assert previous.spread == 0.0
    assert current.spread > 0.0
    # The forming 30m bucket started at 20:00 UTC; action is already at 20:02.
    assert current.bar_time.minute == 2


def test_intrabar_live_uses_long_flat_planner_without_bootstrap_replay():
    previous, current = automanage_signal_pair_v2(
        strategy_key=INTRABAR_30M_LONG_FLAT_STRATEGY_V2,
        points=_flat_history_then_move(),
        market="US Tech 100 NAS · Saxo 4912",
    )
    bootstrap = plan_automanage_step_v2(
        enrollment=_enrollment(),
        state=AutoManageRuntimeStateV2(),
        observed_position=None,
        previous=previous,
        current=current,
        budget_amount=600.0,
        budget_currency="NOK",
    )
    assert bootstrap.outcome_reason == "BOOTSTRAP_NO_REPLAY"
    assert bootstrap.intent is None
    assert bootstrap.decision is None

    live = plan_automanage_step_v2(
        enrollment=_enrollment(),
        state=AutoManageRuntimeStateV2(last_evaluated_bar_time=previous.bar_time),
        observed_position=None,
        previous=previous,
        current=current,
        budget_amount=600.0,
        budget_currency="NOK",
    )
    assert live.outcome_reason == "FRESH_MACD_CROSS"
    assert live.intent is not None
    assert live.intent.signal == "CROSS_UP"
    assert live.intent.target_direction == "LONG"
    assert live.decision is not None
    assert live.decision.action == "OPEN"


def test_closed_30m_paper_controls_do_not_mislabel_intrabar_as_replay():
    assert INTRABAR_30M_LONG_FLAT_STRATEGY_V2 not in PAPER_BENCHMARK_STRATEGY_KEYS_V2
