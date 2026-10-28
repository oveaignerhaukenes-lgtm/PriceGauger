"""Causal price-shape gate does not use future candles to label current form."""
from datetime import datetime,timedelta,timezone
from math import sin
from types import SimpleNamespace
from pathlib import Path

from autotrader_v3_trade_gate_research_v1 import (
    GateWindow,build_causal_gate_windows,evaluate_trade_gate_train_holdout,
)

START=datetime(2026,10,27,tzinfo=timezone.utc)


def synth(minutes=180):
    out=[]
    for i in range(minutes):
        at=START+timedelta(minutes=i)
        price=1000+10*sin(i*.43)+i*.04
        out.append(SimpleNamespace(
            bar_time=at.isoformat(),
            open=price-.2,high=price+.3,low=price-.3,close=price,
        ))
    return out


def points(minutes=180):
    return [
        SimpleNamespace(
            at=START+timedelta(minutes=i),
            nav_nok=10000.+5*(i//30),lots=.01,
        ) for i in range(minutes+1)
    ]


def test_gate_features_from_prior_30m_bars_and_next_result():
    bars=synth();data=points()
    a=build_causal_gate_windows(
        bars=bars,points=data,spread_bps=1.,
        start=START+timedelta(minutes=30),
        end=START+timedelta(minutes=150))
    assert len(a)>=2
    first=a[0]
    assert first.decision_at==START+timedelta(minutes=30)
    assert first.future_until==first.decision_at+timedelta(minutes=30)
    assert first.future_paper_nav_pct>0
    assert 0<=first.price_efficiency<=1
    assert first.class_key in ("OSCILLATING_CHOP","DIRECTIONAL_TREND",
                               "SPREAD_DOMINATED_SWINGS","MIXED_STRUCTURE")
    later=build_causal_gate_windows(
        bars=synth(240),points=points(240),spread_bps=1.,
        start=START+timedelta(minutes=30),
        end=START+timedelta(minutes=150))
    assert later==a


def test_missing_paper_outcome_never_counted_as_flat_or_good():
    bs=synth(150)
    ps=[x for x in points(150)
        if x.at!=START+timedelta(minutes=60)]
    result=build_causal_gate_windows(
        bars=bs,points=ps,spread_bps=1.,
        start=START+timedelta(minutes=30),
        end=START+timedelta(minutes=120))
    assert not any(x.decision_at==START+timedelta(minutes=30) for x in result)


def test_train_and_holdout_purge_and_no_use_of_last_test_outcome():
    sample=[]
    for i in range(48):
        category="OSCILLATING_CHOP" if i%2==0 else "DIRECTIONAL_TREND"
        sample.append(GateWindow(
            START+timedelta(minutes=30*i),
            START+timedelta(minutes=30*(i+1)),
            category,category,.1 if i%2==0 else .9,
            10 if i%2==0 else 0,2.,12.,1.,
            -.8 if i%2==0 else +.9,
        ))
    r=evaluate_trade_gate_train_holdout(sample)
    assert r is not None
    assert r.purged_windows>=1
    actions={k:action for k,action,n,avg in r.trained_actions}
    assert actions=={"OSCILLATING_CHOP":"SKIP","DIRECTIONAL_TREND":"TRADE"}
    assert r.test_windows>=5
    assert r.holdout_predicted_trade_windows>0
    edited=list(sample)
    last=edited[-1]
    edited[-1]=GateWindow(
        last.decision_at,last.future_until,last.class_key,
        last.regime,last.price_efficiency,last.completed_turns,
        last.median_swing_bps,last.range_bps,last.spread_bps,999.)
    r2=evaluate_trade_gate_train_holdout(edited)
    assert r.trained_actions==r2.trained_actions
    assert r.train_cutoff==r2.train_cutoff


def test_sparse_gate_abstains_instead_of_inventing_good_regime():
    tiny=tuple(GateWindow(
        START+timedelta(minutes=i*30),
        START+timedelta(minutes=(i+1)*30),"MIXED","MIXED",.4,2,3.,15.,1.,-1.)
        for i in range(12))
    assert evaluate_trade_gate_train_holdout(tiny) is None


def test_explicitly_no_live_trading_authority():
    s=Path("pages/0_AutoTrader_Gate_Lab.py").read_text()
    code=Path("autotrader_v3_trade_gate_research_v1.py").read_text()
    nav=Path("navigation_config.py").read_text()
    assert "AutoTrader_Gate_Lab" in nav
    assert "Første PAPER-baserte" in s
    assert "evaluer" in s.lower()
    assert "full simulering" in s
    assert "future_until<cutoff" in code
    for forbidden in ("place_order(", "set_live_authority_v3(",
                      "save_autotrader_config_v3("):
        assert forbidden not in code
        assert forbidden not in s
