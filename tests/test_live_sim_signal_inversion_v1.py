"""Inversion experiments: equal signal clocks, opposite directions, fixed-turnover placebo."""
from datetime import datetime,timedelta,timezone
from math import cos,sin
from pathlib import Path
from types import SimpleNamespace

import pytest

from live_sim_signal_inversion_v1 import (
    run_inversion_experiment, _score, _signal_target_events,
)

START=datetime(2026,10,10,tzinfo=timezone.utc)


def bar(i, *, price=100., offset=0):
    p=price+offset
    return SimpleNamespace(
        bar_time=(START+timedelta(minutes=i)).isoformat(),
        open=p,close=p+.02*sin(i/8),high=p+.08,low=p-.08,
        market_name="Tech100 test",volume=20.0,
    )


def prices(n=1070):
    return [bar(i,price=100+0.12*sin(i/19)+0.05*cos(i/35)+.0009*i)
            for i in range(n)]


def test_original_and_inverse_have_same_fill_clock_and_modelled_costs():
    # One valid long entry on the second 1m candle; position then held.
    series=[
        SimpleNamespace(bar_time=(START+timedelta(minutes=i)).isoformat(),
                        open=float(100+i),high=float(102+i),
                        low=float(99+i),close=float(101+i),
                        market_name="T") for i in range(4)
    ]
    signals=((START+timedelta(minutes=1),1),)
    positive=_score(series,signals,start=START,
                    end=START+timedelta(minutes=4),notional=.2,
                    cost_bps=9,mode="original")
    inverse=_score(series,signals,start=START,
                   end=START+timedelta(minutes=4),notional=.2,
                   cost_bps=9,mode="inverse")
    assert positive["gross"]>0
    assert inverse["gross"]<0
    assert positive["turnover"]==inverse["turnover"]==1
    assert positive["changes"]==inverse["changes"]==1
    assert positive["cost"]>0 and inverse["cost"]>0
    assert len(positive["points"])==len(inverse["points"])==4


def test_direct_flip_charges_two_legs_and_random_matches_same_fees():
    # Equal prices imply equal -cost returns no matter the chosen directions.
    series=[SimpleNamespace(bar_time=(START+timedelta(minutes=i)).isoformat(),
             open=100.,high=101.,low=99.,close=100.,market_name="T")
            for i in range(6)]
    events=((START+timedelta(minutes=1),1),
            (START+timedelta(minutes=3),-1))
    all_scores=[_score(series,events,start=START,
                      end=START+timedelta(minutes=6),notional=.2,
                      cost_bps=10,mode=mode,seed=7)
                for mode in ("original","inverse","random")]
    assert all(result["turnover"]==3 for result in all_scores)
    assert len({round(result["net"],10) for result in all_scores})==1
    assert all(result["gross"]==0 for result in all_scores)


def test_pending_signal_fills_only_at_next_available_real_one_minute_open():
    series=[SimpleNamespace(bar_time=(START+timedelta(minutes=i)).isoformat(),
              open=100.,high=101.,low=99.,close=100.,market_name="T")
            for i in (0,1,5,6)]
    events=((START+timedelta(minutes=2),1),
            (START+timedelta(minutes=3),-1))
    score=_score(series,events,start=START,end=START+timedelta(minutes=7),
                 notional=.2,cost_bps=10,mode="original")
    assert score["turnover"]==1  # last SHORT only; no fictitious interim fill
    assert score["changes"]==1
    assert score["active"]==2


def test_full_historical_comparison_is_deterministic_and_has_both_mirrors():
    data=prices()
    a=run_inversion_experiment(data,started_at=START+timedelta(minutes=300),
        ended_at=START+timedelta(minutes=1050),
        random_controls=10,seed=123)
    b=run_inversion_experiment(data,started_at=START+timedelta(minutes=300),
        ended_at=START+timedelta(minutes=1050),
        random_controls=10,seed=123)
    assert a==b
    assert a.completed_bars==750
    assert len(a.rows)==8 and len(a.placebo_medians)==4
    assert {r.variant for r in a.rows}=={"Original","Invertert"}
    assert {r.minutes for r in a.rows}=={5,15}
    for model in ("MACD Flip","Histogram Peak Flip"):
        for minutes in (5,15):
            pair=[r for r in a.rows if r.model==model and r.minutes==minutes]
            assert len(pair)==2
            assert pair[0].traded_legs==pair[1].traded_legs
            assert pair[0].participation_bars==pair[1].participation_bars
            assert pair[0].target_switches==pair[1].target_switches
            assert all(r.cost_pct>=0 for r in pair)
            assert all(len(r.points)==a.completed_bars for r in pair)


def test_holdout_future_does_not_rewrite_earlier_results():
    data=prices()
    options=dict(started_at=START+timedelta(minutes=270),
                 ended_at=START+timedelta(minutes=850),
                 random_controls=4,minutes=(5,),seed=42)
    prior=run_inversion_experiment(data,**options)
    changed=[SimpleNamespace(**{**x.__dict__,
             "open":x.open+5,"close":x.close+5,"high":x.high+5,"low":x.low+5})
             if i>=850 else x for i,x in enumerate(data)]
    after=run_inversion_experiment(changed,**options)
    assert prior==after


def test_no_open_trades_from_incomplete_15m_bucket():
    data=prices(800)
    events=_signal_target_events(data,15,"Histogram Peak Flip")
    assert all(t.minute%15==0 and t.second==0 for t,_ in events)
    assert all(t>=START+timedelta(minutes=15) for t,_ in events)


def test_invalid_costs_and_no_broker_authority():
    with pytest.raises(ValueError):
        run_inversion_experiment(prices(40),started_at=START,
             ended_at=START+timedelta(hours=1),notional_fraction=1.5)
    source=Path("live_sim_signal_inversion_v1.py").read_text()
    for banned in ("place_order(", "configured_client", "from database import",
                   "set_live_enabled", "live_authority_armed_v3"):
        assert banned not in source
    ui=Path("live_sim_signal_inversion_ui_v1.py").read_text()
    assert "render_lab_tv_series" in ui
    assert "run_inversion_experiment" in ui
    assert "Tilfeldige kontrollkjøringer" in ui
