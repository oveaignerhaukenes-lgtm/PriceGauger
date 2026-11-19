"""A STOP/GO candidate must replay actual PAPER inventory and costs."""
from datetime import datetime,timedelta,timezone
from math import sin
from pathlib import Path
from types import SimpleNamespace

import pytest

from strategy_lab_v2_replay import ReplayCostsV2,replay_v3_strategy_v2
from autotrader_v3_trade_gate_research_v1 import (
    GateEvaluation,gate_class_for_completed_bars_v1,
    replay_trained_gate_holdout_v1,
)

START=datetime(2026,11,18,9,0,tzinfo=timezone.utc)
COSTS=ReplayCostsV2(
    point_value_nok=12.,spread_bps=8.,variable_fee_bps=2.,
    fixed_fee_nok=2.,lot_step=.01,max_lots=.03,starting_nav_nok=1000.,
    source="TEST_SCENARIO_NOT_SAXO",
)


def feed(length=280):
    result=[]
    for i in range(length):
        close=100+5*sin(i/12)+i*.012
        opened=close-.15
        result.append(SimpleNamespace(
            bar_time=(START+timedelta(minutes=i)).isoformat(),
            market_name="US Tech100",open=opened,
            high=max(close,opened)+.2,low=min(close,opened)-.2,
            close=close,volume=100,quality_flags=1,
        ))
    return tuple(result)


def _skip_all(cutoff):
    keys=("OSCILLATING_CHOP","DIRECTIONAL_TREND",
          "SPREAD_DOMINATED_SWINGS","MIXED_STRUCTURE")
    return GateEvaluation(
        train_windows=28,test_windows=12,purged_windows=1,
        abstained_windows=0,train_cutoff=cutoff,
        trained_actions=tuple((key,"SKIP",7,-.25) for key in keys),
        holdout_baseline_sum_pct=0.,holdout_only_allowed_sum_pct=0.,
        holdout_skipped_positive_sum_pct=0.,
        holdout_skipped_negative_sum_pct=0.,
        holdout_predicted_trade_windows=0,warning="proxy test",
    )


def test_stop_flattens_existing_paper_position_next_open_with_costs():
    bars=feed()
    baseline=replay_v3_strategy_v2(
        strategy_key="macd-histogram",bars=bars,costs=COSTS)
    opened=next(e for e in baseline.events if e.kind=="OPEN")
    cutoff=opened.at+timedelta(minutes=1)
    seen=[]

    def gate(closed,visible):
        assert all(datetime.fromisoformat(b.bar_time)<closed for b in visible)
        assert len(visible)<=30
        assert datetime.fromisoformat(visible[-1].bar_time)==closed-timedelta(minutes=1)
        seen.append(closed)
        return closed<cutoff

    candidate=replay_v3_strategy_v2(
        strategy_key="macd-histogram",bars=bars,costs=COSTS,
        paper_gate=gate)
    assert len(seen)==len(bars)
    assert [p.lots for p in candidate.points if p.at<=cutoff]==[
        p.lots for p in baseline.points if p.at<=cutoff]
    assert any(e.kind=="CLOSE" and e.at==cutoff
               for e in candidate.events)
    assert all(abs(p.lots)<1e-9 for p in candidate.points if p.at>cutoff)
    assert all(e.kind!="OPEN" for e in candidate.events if e.at>=cutoff)
    assert candidate.total_cost_nok==pytest.approx(
        sum(e.cost_nok for e in candidate.events))


def test_full_holdout_uses_frozen_train_policy_and_matched_initial_nav():
    bars=feed()
    baseline=replay_v3_strategy_v2(
        strategy_key="macd-histogram",bars=bars,costs=COSTS)
    cutoff=START+timedelta(minutes=200)
    evaluation=_skip_all(cutoff)
    comparison=replay_trained_gate_holdout_v1(
        bars=bars,costs=COSTS,strategy_key="macd-histogram",
        timeframe="2m",evaluation=evaluation,baseline=baseline)
    assert comparison.cutoff==cutoff
    assert comparison.cost_source=="TEST_SCENARIO_NOT_SAXO"
    assert comparison.gated_orders<=comparison.baseline_orders+1
    assert comparison.gated_minus_baseline_pct==pytest.approx(
        comparison.gated_holdout_pct-comparison.baseline_holdout_pct)
    assert comparison.gated_cost_nok>=0
    assert comparison.baseline_cost_nok>=0
    assert "not Saxo" in comparison.warning


def test_gate_class_requires_contiguous_completed_bars_no_future():
    bars=feed(60)
    first=gate_class_for_completed_bars_v1(bars[:30],COSTS.spread_bps)
    assert first in {"OSCILLATING_CHOP","DIRECTIONAL_TREND",
                     "SPREAD_DOMINATED_SWINGS","MIXED_STRUCTURE"}
    later=feed(80)
    assert gate_class_for_completed_bars_v1(later[:30],COSTS.spread_bps)==first
    broken=list(bars[:30])
    broken[4]=SimpleNamespace(
        **{**vars(broken[4]),"bar_time":(START+timedelta(minutes=100)).isoformat()})
    assert gate_class_for_completed_bars_v1(broken,COSTS.spread_bps) is None
    assert gate_class_for_completed_bars_v1(bars[:29],COSTS.spread_bps) is None


def test_full_replay_remains_paper_only():
    code=Path("autotrader_v3_trade_gate_research_v1.py").read_text()
    assert "paper_gate=paper_gate" in code
    assert "PAPER next-open" in code
    for forbidden in ("place_order(","set_live_authority_v3("):
        assert forbidden not in code
