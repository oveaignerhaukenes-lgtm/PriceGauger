"""Mechanical allocation research: no future, independent shadow, 0% recovery."""
from datetime import datetime, timedelta, timezone
from math import sin
from types import SimpleNamespace

import pytest

from mechanical_capital_manager_v1 import (
    ObserverPoint, StrategyObserver, replay_mechanical_allocator,
)
from mechanical_capital_manager_observer_v1 import (
    SUPPORTED_SHADOW_KEYS, latest_contiguous_completed_1m_v1,
    shadow_observer_from_completed_bars_v1,
)

START = datetime(2026,10,26,9,0,tzinfo=timezone.utc)


def observer(instance="A", model="m1", values=(), cap=100.):
    return StrategyObserver(
        instance,model,"PAPER_INDEX_1X",cap,
        tuple(ObserverPoint(START+timedelta(minutes=15*i),float(v))
              for i,v in enumerate(values))
    )


def test_per_one_percent_changes_by_ten_percent_of_manual_cap():
    t=replay_mechanical_allocator([observer(values=[100,101,102.01,101.00,100,99,100,101])])
    assert t.status=="PAPER_ONLY"
    d=t.decisions
    assert d[0].suggested_exposure_pct == pytest.approx(60.,rel=.001)
    assert d[1].suggested_exposure_pct == pytest.approx(70.,rel=.001)
    assert d[2].suggested_exposure_pct == pytest.approx(60.098,abs=.02)
    assert all(0<=x.suggested_exposure_pct<=100 for x in d)


def test_negative_ten_percent_shadow_drawdown_goes_to_zero_and_observer_recovers():
    vals=[100,99,98,97,96,94,89,90,91,92,93,94,95,96,97,98]
    t=replay_mechanical_allocator([observer(values=vals)])
    assert any(x.state=="SHADOW_STOP" for x in t.decisions)
    assert any(x.suggested_exposure_pct==0 for x in t.decisions)
    assert any(x.state=="PAPER_REENTRY" for x in t.decisions)
    stop_i=next(i for i,x in enumerate(t.decisions) if x.state=="SHADOW_STOP")
    resume_i=next(i for i,x in enumerate(t.decisions) if x.state=="PAPER_REENTRY")
    assert stop_i < resume_i
    assert all(x.suggested_exposure_pct==0 for x in t.decisions[stop_i:resume_i])
    assert t.decisions[resume_i].suggested_exposure_pct == pytest.approx(10)


def test_future_appends_do_not_change_past_decisions():
    vals=[100,101,99,100,98,99,100,102,101,103,101,104]
    a=replay_mechanical_allocator([observer(values=vals[:9])])
    b=replay_mechanical_allocator([observer(values=vals)])
    assert b.decisions[:len(a.decisions)] == a.decisions
    assert b.portfolio_equity[:len(a.portfolio_equity)] == a.portfolio_equity


def test_two_models_and_strict_currency_bounds_and_correlation():
    vals=[100]
    opp=[100]
    for i in range(1,24):
        ret=.01 if i%2 else -.01
        vals.append(vals[-1]*(1+ret))
        opp.append(opp[-1]*(1-ret))
    a=observer("a","V21",vals,75)
    b=observer("b","RHYTHM",opp,45)
    t=replay_mechanical_allocator([a,b])
    assert t.evaluated_slots==23
    assert len(t.correlations)==1
    assert t.correlations[0][2] < -.9
    assert max(x.suggested_exposure_pct for x in t.decisions if x.instance_id=="a") <=75
    with pytest.raises(ValueError, match="duplicate"):
        replay_mechanical_allocator([a,a])
    with pytest.raises(ValueError, match="currencies"):
        replay_mechanical_allocator([a,StrategyObserver("c","x","USD",100.,b.points)])


def test_no_fabrication_across_missing_15min_slot():
    x=observer(values=[100,101,102,103,104,105,106,107])
    points=x.points[:4]+x.points[5:]
    t=replay_mechanical_allocator([StrategyObserver(
        x.instance_id,x.strategy_key,x.currency,x.manual_slider_pct,points
    )])
    assert any(z.state=="GAP_PAUSE" for z in t.decisions)
    # No synthetic skipped 15m price return is added.
    assert t.evaluated_slots == 5
    assert all(z.suggested_exposure_pct == 0 for z in t.decisions if z.state=="GAP_PAUSE")


def test_cost_cannot_improve_identical_manager_returns():
    vals=[100,101,100,101,99,101,100,99,100,101,102,101]
    a=replay_mechanical_allocator([observer(values=vals)],turnover_cost_bps=0.)
    b=replay_mechanical_allocator([observer(values=vals)],turnover_cost_bps=25.)
    assert b.portfolio_equity[-1][1] <= a.portfolio_equity[-1][1]
    assert b.fixed_equity == a.fixed_equity


def test_requires_independent_shadow_while_in_zero():
    x=observer(values=[100,98,97,96,95,94,90,89])
    with pytest.raises(ValueError,match="independent PAPER"):
        replay_mechanical_allocator([StrategyObserver(
            x.instance_id,x.strategy_key,x.currency,x.manual_slider_pct,
            x.points,independent_of_allocation=False
        )])
    bad=observer(values=[100,101,0,100,100,100])
    with pytest.raises(ValueError,match="positive finite"):
        replay_mechanical_allocator([bad])


def canonical_bars(n=270, gap_at=None):
    out=[]
    for i in range(n):
        t=START+timedelta(minutes=i+(10 if gap_at is not None and i>=gap_at else 0))
        p=20000.+35*sin(i/17.)+3*sin(i/3.)
        out.append(SimpleNamespace(
            market_name="US Tech 100 NAS",bar_time=t.isoformat(),
            close=p,open=p,high=p+3,low=p-3,
        ))
    return out


@pytest.mark.parametrize("strategy",SUPPORTED_SHADOW_KEYS)
def test_independent_1m_observer_emits_only_completed_15m_points(strategy):
    bars=latest_contiguous_completed_1m_v1(
        canonical_bars(),asof=START+timedelta(minutes=270)
    )
    s=shadow_observer_from_completed_bars_v1(
        bars,instance_id="pilot",strategy_key=strategy,
        manual_slider_pct=83.,cost_roundtrip_bps=8.,
    )
    assert s.strategy_key==strategy
    assert s.independent_of_allocation
    assert s.points
    assert all(x.at.minute%15==0 and x.shadow_equity>0 for x in s.points)
    assert s.points[-1].at <= START+timedelta(minutes=270)
    assert len(s.points)>=6
    assert replay_mechanical_allocator([s]).status=="PAPER_ONLY"


def test_1m_observer_never_bridges_session_gap_and_requires_closed_bars():
    bars=canonical_bars(270,gap_at=125)
    result=latest_contiguous_completed_1m_v1(
        bars,asof=START+timedelta(minutes=280)
    )
    assert len(result)==145
    assert result[0].bar_time == bars[125].bar_time
    cut=latest_contiguous_completed_1m_v1(
        canonical_bars(270),asof=START+timedelta(minutes=100)
    )
    assert len(cut)==100
    with pytest.raises(ValueError,match="unsupported"):
        shadow_observer_from_completed_bars_v1(
            cut,instance_id="p",strategy_key="aen-inference",
            manual_slider_pct=100
        )
