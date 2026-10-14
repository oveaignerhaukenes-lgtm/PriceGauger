"""AEn explanatory churn metrics and structural fill protection."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import aen_replay_v1 as engine
from aen_core_v1 import StructureEvent
from aen_diagnostics_v1 import turnover_diagnostics

START=datetime(2026,10,14,tzinfo=timezone.utc)


def test_fast_flat_reentries_are_classified_without_counting_scaling():
    def fill(minute,units):
        return ((START+timedelta(minutes=minute)).isoformat(),
                units,"SIM",5,100.0)
    report=SimpleNamespace(
        fills=(fill(1,1),fill(2,2),fill(3,0),fill(4,-1),
               fill(5,0),fill(9,-1),fill(16,0),fill(20,1)),
        turnover_units=12,gross_pct=1.2,return_pct=.8)
    result=turnover_diagnostics(report)
    assert result.total_units==12
    assert result.round_trips==3
    assert result.exit_to_reentry_under_1m==1
    assert result.exit_to_reentry_under_2m==1
    assert result.exit_to_reentry_under_5m==3
    assert result.opposite_reentry_under_5m==2
    assert result.estimated_cost_drag_pct==.4


def test_protected_higher_low_is_not_forgotten_at_fill(monkeypatch):
    bars=[
        SimpleNamespace(
            bar_time=(START+timedelta(minutes=i)).isoformat(),
            open=100,close=(98 if i==5 else 100),
            high=100.5,low=(97.5 if i==5 else 99.5),
            volume=10,market_name="Tech100",
        )
        for i in range(10)
    ]
    def bullish(candles):
        return {c.end:engine.Indicator(c.end,.3,.2,70,60) for c in candles}
    def events(*_):
        return {
            START+timedelta(minutes=3):(
                StructureEvent("HH",1,2,105.0),),
            START+timedelta(minutes=5):(
                StructureEvent("HL",3,4,99.0),),
        }
    monkeypatch.setattr(engine,"_indicators",bullish)
    monkeypatch.setattr(engine,"_structure",events)
    r=engine.replay(engine.AEnPaperConfig(minutes=1,structure_minutes=1,
                                         max_units=1),bars,started_at=START)
    reasons=[fill[2] for fill in r.fills]
    assert reasons[:2]==["HH_HL_OPEN","PROTECTED_SWING_FLAT"]
    assert r.fills[0][1]==1 and r.fills[1][1]==0


def test_2m_confirmation_does_not_reuse_stale_signal(monkeypatch):
    bars=[SimpleNamespace(
        bar_time=(START+timedelta(minutes=i)).isoformat(),
        market_name="Tech100",open=100,close=(99.5 if i==50 else 100),
        high=100.5,low=(99 if i==50 else 99.5),volume=10)
        for i in range(58)]
    def indicators(candles):
        tf=(int((candles[1].end-candles[0].end).total_seconds()/60)
            if len(candles)>1 else 30)
        obs={}
        for c in candles:
            minute=int((c.end-START).total_seconds()/60)
            if tf==1:
                hist,prev=(-.3,.1) if minute==51 else (-.3,-.2)
            elif tf==2:
                hist,prev=(-.3,-.2)
            else:
                hist,prev=(.3,.4)
            obs[c.end]=engine.Indicator(c.end,hist,prev,30,20)
        return obs
    monkeypatch.setattr(engine,"_indicators",indicators)
    monkeypatch.setattr(engine,"_structure",lambda *_:{})
    cfg=engine.AEnPaperConfig(minutes=10,structure_minutes=1,max_units=3,
                              confirmation_ladder=True,pulse_min_pct=.12)
    r=engine.replay(cfg,bars,started_at=START)
    assert r.fills[0][2]=="PULSE_1M_PROBE"
    if len(r.fills)>1:
        confirm=r.fills[1]
        # A 2m signal can authorize a future order only at closed even-minute.
        signal_at=engine.utc(confirm[0])
        assert (signal_at-START).total_seconds()/60%2==0
