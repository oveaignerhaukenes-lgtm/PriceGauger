"""Strong-opposite V2.2 and causal 1-second BBO momentum event-study tests."""
from datetime import datetime,timedelta,timezone
from math import sin
from types import SimpleNamespace

import pytest

import autotrader_v3_macd_stoch_v22_flip as v22
from autotrader_v3_macd_stoch_v2 import MacdStochV2DecisionV3
from autotrader_v3_domain import (
    TargetInventoryV3,AccountBoundaryV3,CapitalAllocationV3,
    DecisionSnapshotV3,ControlModeV3,
)
from autotrader_v3_execution_plan_v1 import plan_execution_v3
from autotrader_v3_macd_trailing_v1 import MacdTrailingConfigV3
from autotrader_v3_registry_v1 import STRATEGIES_V3,live_config_issues_v3
from autotrader_v3_strategy_registry_v1 import strategy_adapter_v3
from autotrader_v3_strategy_sizing_v1 import DEFAULT_MAX_TRANCHES_V3
from tech100_second_impulse_research_v1 import (
    prepare_second_quotes,study_thresholds,summarize_thresholds,
    chronological_split_at,
)

START=datetime(2026,10,27,6,0,tzinfo=timezone.utc)


def mocked_base(action,score):
    return MacdStochV2DecisionV3(
        target=TargetInventoryV3(0.),action=action,reason="controlled base",
        spread=score,composite_score=score,macd_component=score,
        stoch_component=0.,
    )


def test_v22_immediate_target_only_strong_opposite(monkeypatch):
    monkeypatch.setattr(v22,"macd_stoch_v21_target_v3",
                        lambda **kwargs: mocked_base("OPPOSITE_FLAT",-.41))
    got=v22.macd_stoch_v22_flip_target_v3(
        current_target=TargetInventoryV3(.04),observation=object(),
        config=MacdTrailingConfigV3(tranche=.01,max_inventory=.1))
    assert got.target.amount==pytest.approx(-.01)
    assert got.action=="FLIP_TARGET"
    assert "CONFIRM_FLAT" in got.reason
    assert "controlled base" in got.reason


@pytest.mark.parametrize("score",(.001,.11,.22,.299))
def test_v22_weak_opposite_goes_flat_not_micro_flip(monkeypatch,score):
    monkeypatch.setattr(v22,"macd_stoch_v21_target_v3",
                        lambda **kwargs: mocked_base("OPPOSITE_FLAT",-score))
    got=v22.macd_stoch_v22_flip_target_v3(
        current_target=TargetInventoryV3(.02),observation=object())
    assert got.target.amount==0.
    assert got.action=="OPPOSITE_FLAT"


def test_v22_same_direction_build_and_warmup_unchanged(monkeypatch):
    calls=[]
    def fake(**kwargs):
        calls.append(kwargs)
        return mocked_base("HOLD_BUILD_DECELERATING",.51)
    monkeypatch.setattr(v22,"macd_stoch_v21_target_v3",fake)
    actual=v22.macd_stoch_v22_flip_target_v3(
        current_target=TargetInventoryV3(.02),observation=object(),
        previous_observation=None,bars=[])
    assert actual.action=="HOLD_BUILD_DECELERATING"
    assert len(calls)==1


def test_v22_catalog_and_order_plan_preserve_reconcile_barrier():
    key=v22.STRATEGY_KEY_V3
    assert key=="macd-stoch-v2-2-flip"
    assert key in (s.runtime_key for s in STRATEGIES_V3 if s.runtime_ready)
    assert strategy_adapter_v3(key).live_route_enabled
    assert not live_config_issues_v3(strategy_key="macd-stoch-v2-2-flip",
                                    timeframe="1m",control_mode="Manuell",
                                    modifiers=())
    assert DEFAULT_MAX_TRANCHES_V3==10
    broker=AccountBoundaryV3("A",4912,"CfdOnIndex")
    snap=DecisionSnapshotV3(
        trader_id="test",account=broker,mode=ControlModeV3.DETERMINISTIC,
        strategy_key=key,capital_allocation=CapitalAllocationV3(100),
        base_target=TargetInventoryV3(-.01),
        effective_target=TargetInventoryV3(-.01),
        risk_approved_target=TargetInventoryV3(-.01),
        actual_inventory=TargetInventoryV3(+.04),
        pending_delta=-.05,
    )
    plan=plan_execution_v3(snap)
    assert [x.action for x in plan.steps]==["CLOSE","CONFIRM_FLAT","OPEN"]


def synthetic_quotes(n=900, gap=None):
    out=[]
    for i in range(n):
        if gap is not None and gap<=i<gap+30:
            continue
        if i<200:
            price=20000.
        elif i<280:
            price=20023.+(i-200)*.38
        elif i<400:
            price=20053.-(i-280)*.30
        elif i<530:
            price=20017.-(i-400)*.34
        else:
            price=19975.+4*sin(i/35.)
        t=START+timedelta(seconds=i)
        out.append(dict(
            quote_at=t.isoformat(),
            received_at=(t+timedelta(milliseconds=300)).isoformat(),
            bid=price-1.,ask=price+1.,
        ))
    return out


def test_causal_threshold_crossing_and_observed_retracement():
    sessions=prepare_second_quotes(synthetic_quotes())
    assert len(sessions)==1
    outcomes=study_thresholds(
        sessions,lookbacks=(10,),thresholds=(10.,),
        horizons=(30,60,120),
    )
    assert outcomes
    assert len(outcomes)%3==0
    assert any(x.direction=="LONG" for x in outcomes)
    for e in outcomes:
        assert e.triggered_at>=START+timedelta(seconds=200)
        assert e.horizon_seconds in (30,60,120)
        assert e.bidask_spread_bps>0
        assert e.peak_seconds>=0
        assert e.max_continuation_bps>=0
    cutoff=chronological_split_at(sessions)
    out=summarize_thresholds(outcomes,chronological_cutoff=cutoff)
    assert all(g.events>=1 for g in out)
    assert all(g.profitable_fraction is None or 0<=g.profitable_fraction<=1
               for g in out)


def test_future_quotes_never_change_past_completed_event_scores():
    allrows=synthetic_quotes(900)
    a=prepare_second_quotes(allrows[:700])
    b=prepare_second_quotes(allrows)
    ea=study_thresholds(a,lookbacks=(10,),thresholds=(10.,),
                        horizons=(30,60,120))
    eb=study_thresholds(b,lookbacks=(10,),thresholds=(10.,),
                        horizons=(30,60,120))
    lookup={(e.triggered_at,e.horizon_seconds):e for e in eb}
    assert ea and all(lookup.get((x.triggered_at,x.horizon_seconds))==x for x in ea)


def test_gap_splits_session_and_does_not_invent_quotes():
    groups=prepare_second_quotes(synthetic_quotes(900,gap=300))
    assert len(groups)>=2
    assert all(all((b.at-a.at).total_seconds()<=4 for a,b in zip(seg,seg[1:]))
               for seg in groups)
    results=study_thresholds(groups,lookbacks=(10,),thresholds=(10.,),
                             horizons=(30,60,120))
    assert all(not (START+timedelta(seconds=300)<=x.triggered_at
                    <START+timedelta(seconds=330)) for x in results)


def test_invalid_bbo_rejected_and_delayed_feed_excluded():
    rows=synthetic_quotes(300)
    swapped=list(rows)
    swapped[10]=dict(swapped[10],ask=swapped[10]["bid"]-.01)
    with pytest.raises(ValueError,match="crossed"):
        prepare_second_quotes(swapped)
    repeats=rows+[rows[-1]]
    with pytest.raises(ValueError,match="duplicate"):
        prepare_second_quotes(repeats)
    delayed=list(rows)
    delayed[220]=dict(delayed[220],
                      received_at=(START+timedelta(seconds=229)).isoformat())
    sessions=prepare_second_quotes(delayed)
    assert sessions
    assert not any(q.at==START+timedelta(seconds=220)
                   for part in sessions for q in part)


def test_insufficient_data_and_unknown_parameters_fail_closed():
    with pytest.raises(ValueError,match="insufficient"):
        chronological_split_at(prepare_second_quotes(synthetic_quotes(250)))
    groups=prepare_second_quotes(synthetic_quotes(700))
    with pytest.raises(ValueError,match="unsupported threshold"):
        study_thresholds(groups,thresholds=(1000.,))
    with pytest.raises(ValueError,match="unsupported lookback"):
        study_thresholds(groups,lookbacks=(2,))
