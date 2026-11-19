"""Three PAPER rounds: embargoed training and real simulated close/re-entry."""
from datetime import datetime, timedelta, timezone
from math import sin
from types import SimpleNamespace

from autotrader_v3_trade_gate_research_v1 import GateWindow
from autotrader_v3_trade_gate_rounds_v1 import (
    _train_actions, evaluate_full_flat_replay_rounds,
)
from strategy_lab_v2_replay import ReplayCostsV2, replay_v3_strategy_v2


START = datetime(2026, 11, 18, tzinfo=timezone.utc)
COSTS = ReplayCostsV2(point_value_nok=10., spread_bps=4.,
                       variable_fee_bps=0., fixed_fee_nok=0.,
                       lot_step=.01, max_lots=.03, starting_nav_nok=10000.)


def _bars(count=1300):
    rows = []
    for i in range(count):
        p = 20000 + 32 * sin(i / 9) + 14 * sin(i / 29) + i * .01
        rows.append(SimpleNamespace(
            market_name="US Tech100", bar_time=(START + timedelta(minutes=i)).isoformat(),
            open=p-.3, high=p+.5, low=p-.5, close=p, volume=1.,
        ))
    return rows


def _windows():
    return [GateWindow(
        decision_at=START + timedelta(minutes=30 * (i+1)),
        future_until=START + timedelta(minutes=30 * (i+2)),
        class_key="UNPROFITABLE" if i % 2 == 0 else "PROFITABLE",
        regime="SYNTHETIC", price_efficiency=.4,
        completed_turns=4, median_swing_bps=5., range_bps=18.,
        spread_bps=4.,future_paper_nav_pct=(-1. if i % 2 == 0 else 1.),
    ) for i in range(35)]


def test_predeclared_rules_distinguish_blacklist_average_and_confidence():
    sample = _windows()
    # Six small winners are enough for mean-allowed but not for the
    # confidence rule; losing shapes must be blacklisted consistently.
    six_winners = [x for x in sample if x.class_key == "PROFITABLE"][:6]
    six_losers = [x for x in sample if x.class_key == "UNPROFITABLE"][:6]
    train = six_winners + six_losers
    assert _train_actions(train,"LOSS_BLACKLIST")["PROFITABLE"][0] == "TRADE"
    assert _train_actions(train,"LOSS_BLACKLIST")["UNPROFITABLE"][0] == "SKIP"
    assert _train_actions(train,"MEAN_CLASS")["PROFITABLE"][0] == "TRADE"
    assert _train_actions(train,"CONFIDENT_ONLY")["PROFITABLE"][0] == "SKIP"
    assert _train_actions(six_winners+six_winners,"CONFIDENT_ONLY")["PROFITABLE"][0] == "TRADE"


def test_gate_callback_flatten_and_next_open_costs_in_paper_only():
    bs = _bars(290)
    baseline = replay_v3_strategy_v2(
        strategy_key="macd-histogram", bars=bs, costs=COSTS, timeframe="2m")
    allowed = replay_v3_strategy_v2(
        strategy_key="macd-histogram", bars=bs, costs=COSTS,
        timeframe="2m",decision_gate=lambda at: True)
    assert allowed.events == baseline.events
    assert allowed.points == baseline.points
    blocked = replay_v3_strategy_v2(
        strategy_key="macd-histogram", bars=bs, costs=COSTS,
        timeframe="2m",decision_gate=lambda at: False)
    assert blocked.trades == 0
    assert all(p.lots == 0 for p in blocked.points)
    assert blocked.net_return_pct == 0.


def test_three_frozen_rules_compare_real_simulated_holdout_nav_and_costs():
    bs = _bars()
    baseline = replay_v3_strategy_v2(
        strategy_key="macd-histogram", bars=bs, costs=COSTS, timeframe="2m")
    sample = _windows()
    rounds = evaluate_full_flat_replay_rounds(
        windows=sample,baseline=baseline,bars=bs,
        strategy_key="macd-histogram",timeframe="2m",costs=COSTS)
    assert tuple(x.name for x in rounds) == (
        "LOSS_BLACKLIST","MEAN_CLASS","CONFIDENT_ONLY")
    assert all(x.eligible_windows + x.blocked_windows == 11 for x in rounds)
    assert all(x.gated_orders >= 0 and x.gated_execution_cost_nok >= 0 for x in rounds)
    assert all(abs(x.holdout_gated_nok-x.holdout_baseline_nok-x.holdout_delta_nok)<1e-8
               for x in rounds)
    assert any(x.blocked_windows > 0 for x in rounds)
    assert all(x.gated_result.cost_source == "MANUAL_SCENARIO" for x in rounds)
    assert all(not any(e.kind == "OPEN" and e.after_lots == 0
                           for e in x.gated_result.events) for x in rounds)

    # Any edit to *future* holdout outcomes must not change rules or fills.
    contaminated = list(sample)
    for i in range(25, len(contaminated)):
        v = contaminated[i]
        contaminated[i] = GateWindow(
            v.decision_at,v.future_until,v.class_key,v.regime,
            v.price_efficiency,v.completed_turns,v.median_swing_bps,
            v.range_bps,v.spread_bps,1000.)
    again = evaluate_full_flat_replay_rounds(
        windows=contaminated,baseline=baseline,bars=bs,
        strategy_key="macd-histogram",timeframe="2m",costs=COSTS)
    assert [(x.decisions,x.eligible_windows,x.holdout_gated_nok) for x in rounds] == [
        (x.decisions,x.eligible_windows,x.holdout_gated_nok) for x in again]
