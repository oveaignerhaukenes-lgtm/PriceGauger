"""AEn causal replay / deterministic inventory contract tests (SIM-only)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import aen_replay_v1 as aen
from aen_core_v1 import StructureEvent

BASE = datetime(2026, 10, 13, tzinfo=timezone.utc)


def bar(i, *, op=100, cl=100, volume=10):
    return SimpleNamespace(
        bar_time=(BASE + timedelta(minutes=i)).isoformat(),
        market_name="US Tech 100 NAS", open=op, close=cl,
        high=max(op, cl) + .01, low=min(op, cl) - .01, volume=volume,
    )


def observations(candles):
    return {b.end:aen.Indicator(b.end, 0.15, 0.1, 80, 70) for b in candles}


def structure(indexes):
    return {BASE + timedelta(minutes=i):tuple(
        StructureEvent(kind, i-2, i-1, price) for kind, price in values
    ) for i,values in indexes.items()}


def test_aggregation_discards_incomplete_bucket_and_bad_time():
    bars = [bar(0),bar(1),bar(3),bar(4),bar(5)]
    aggregated = aen._aggregate(bars,2)
    assert len(aggregated) == 2  # buckets [0,1] and [4,5] are complete; [2,3] is not
    assert [b.end for b in aggregated] == [BASE + timedelta(minutes=2), BASE + timedelta(minutes=6)]


def test_indicator_no_future_bar_access():
    candles = aen._aggregate([bar(i,cl=100+i/100) for i in range(50)],1)
    prefix = aen._indicators(candles[:40])
    complete = aen._indicators(candles)
    assert prefix
    assert all(k <= candles[39].end for k in prefix)
    assert all(prefix[k] == complete[k] for k in prefix)


def test_broker_free_exports():
    content = Path("aen_replay_v1.py").read_text()
    for banned in ("configured_client", "place_order", "from database import",
                   "import saxo", "live_authority_armed"):
        assert banned not in content


def test_open_then_confirmed_hl_add_and_no_same_event_double_add(monkeypatch):
    monkeypatch.setattr(aen,"_indicators",observations)
    monkeypatch.setattr(aen,"_structure",lambda *_:structure({
        3:[("HH",102)],4:[("HL",98)],
        6:[("HH",103)],7:[("HL",99)],
    }))
    cfg=aen.AEnPaperConfig(minutes=1,structure_minutes=1,max_units=3)
    result=aen.replay(cfg,[bar(i) for i in range(11)],started_at=BASE)
    assert [(n,r) for _t,n,r,_tf,_p in result.fills] == [
        (1,"HH_HL_OPEN"),(2,"HH_HL_ADD")
    ]
    assert result.turnover_units==2
    assert all(abs(row[3])<=3 for row in result.points)


def test_cap_one_never_scales(monkeypatch):
    monkeypatch.setattr(aen,"_indicators",observations)
    monkeypatch.setattr(aen,"_structure",lambda *_:structure({
        3:[("HH",102)],4:[("HL",98)],
        6:[("HH",103)],7:[("HL",99)],
    }))
    report=aen.replay(aen.AEnPaperConfig(minutes=1,structure_minutes=1,max_units=1),
                      [bar(i) for i in range(11)],started_at=BASE)
    assert report.turnover_units==1
    assert all(abs(row[3])<=1 for row in report.points)


def test_LL_reduce_then_LH_flat_without_reverse(monkeypatch):
    monkeypatch.setattr(aen,"_indicators",observations)
    monkeypatch.setattr(aen,"_structure",lambda *_:structure({
        3:[("HH",105)],4:[("HL",90)],
        6:[("HH",110)],7:[("HL",91)],
        9:[("LL",89)],11:[("LH",102)],
    }))
    report=aen.replay(aen.AEnPaperConfig(minutes=1,structure_minutes=1,max_units=3),
                      [bar(i) for i in range(14)],started_at=BASE)
    changes=[(n,r) for _t,n,r,_tf,_p in report.fills]
    assert changes == [(1,"HH_HL_OPEN"),(2,"HH_HL_ADD"),
                       (1,"STRUCTURE_LL_REDUCE"),(0,"STRUCTURE_LH_FLAT")]
    assert -1 not in [f[1] for f in report.fills]


def test_opposite_macd_regime_flats_first(monkeypatch):
    def signals(candles):
        out={}
        for c in candles:
            idx=int((c.end-BASE).total_seconds()/60)
            sign=-1 if idx>=7 else 1
            out[c.end]=aen.Indicator(c.end,.15*sign,.12*sign,75,65)
        return out
    monkeypatch.setattr(aen,"_indicators",signals)
    monkeypatch.setattr(aen,"_structure",lambda *_:structure({
        3:[("HH",105)],4:[("HL",90)],
        8:[("LL",88)],9:[("LH",98)],
    }))
    result=aen.replay(aen.AEnPaperConfig(minutes=1,structure_minutes=1),
                      [bar(i) for i in range(12)],started_at=BASE)
    fills=[(n,r) for _t,n,r,_tf,_p in result.fills]
    assert (1,"HH_HL_OPEN") in fills
    assert (0,"MACD_REVERSE_FLAT") in fills
    # Opposite entry only after verified simulation FLAT and LL/LH.
    if any(n<0 for n,_ in fills):
        assert fills.index((0,"MACD_REVERSE_FLAT")) < next(i for i,(n,_) in enumerate(fills) if n<0)


def test_against_impulse_with_real_rising_volume_exits_next_open(monkeypatch):
    monkeypatch.setattr(aen,"_indicators",observations)
    monkeypatch.setattr(aen,"_structure",lambda *_:structure({
        3:[("HH",105)],5:[("HL",90)]
    }))
    bars=[bar(i) for i in range(12)]
    bars[8]=bar(8,op=100,cl=99.0,volume=100)
    cfg=aen.AEnPaperConfig(minutes=1,structure_minutes=1,impulse_enabled=True,
                           impulse_pct=.3,max_units=1)
    result=aen.replay(cfg,bars,started_at=BASE)
    assert any(d[1]=="IMPULSE_VOLUME_EXIT" for d in result.decisions)
    exit_fill=next(x for x in result.fills if x[2]=="IMPULSE_VOLUME_EXIT")
    assert exit_fill[0]==(BASE+timedelta(minutes=9)).isoformat()


def test_missing_volume_impulse_waits_with_bound(monkeypatch):
    monkeypatch.setattr(aen,"_indicators",observations)
    monkeypatch.setattr(aen,"_structure",lambda *_:structure({
        3:[("HH",105)],5:[("HL",90)]
    }))
    bars=[bar(i,volume=None) for i in range(15)]
    for i in range(8,12):
        bars[i]=bar(i,op=100,cl=99.3,volume=None)
    cfg=aen.AEnPaperConfig(minutes=1,structure_minutes=1,impulse_enabled=True,
                           impulse_pct=.3,retrace_wait_bars=2,
                           hard_adverse_pct=1.0)
    result=aen.replay(cfg,bars,started_at=BASE)
    assert not any(d[1]=="IMPULSE_VOLUME_EXIT" for d in result.decisions)
    assert any(d[1]=="IMPULSE_TIMEOUT_EXIT" for d in result.decisions)


def test_fixed_fee_is_charged_only_on_quantity_and_next_open(monkeypatch):
    monkeypatch.setattr(aen,"_indicators",observations)
    monkeypatch.setattr(aen,"_structure",lambda *_:structure({
        3:[("HH",105)],4:[("HL",90)]
    }))
    bars=[bar(i) for i in range(8)]
    bars[3]=bar(3,op=100,cl=110)  # signal at close cannot earn this same candle
    cfg=aen.AEnPaperConfig(minutes=1,structure_minutes=1,costs_enabled=False)
    gross=aen.replay(cfg,bars,started_at=BASE)
    net=aen.replay(aen.AEnPaperConfig(minutes=1,structure_minutes=1,costs_enabled=True),bars,started_at=BASE)
    assert net.return_pct<gross.return_pct
    assert net.executions==gross.executions
    assert net.total_cost_pct>0


def test_timeframe_auto_never_places_trade_just_for_switch(monkeypatch):
    def cooling(candles):
        return {x.end:aen.Indicator(x.end,1-.005*i,1-.005*(i-1),75,65)
                for i,x in enumerate(candles)}
    monkeypatch.setattr(aen,"_indicators",cooling)
    monkeypatch.setattr(aen,"_structure",lambda *_:{})
    r=aen.replay(aen.AEnPaperConfig(minutes=5,structure_minutes=1,adaptive=True,
                                    dwell_minutes=1),[bar(i) for i in range(120)],started_at=BASE)
    assert r.executions==0 and r.turnover_units==0
    assert len(r.timeframe_changes)>=1


def test_config_validation():
    with pytest.raises(ValueError):
        aen.AEnPaperConfig(minutes=3)
    with pytest.raises(ValueError):
        aen.AEnPaperConfig(unit_exposure=-1)
    with pytest.raises(ValueError):
        aen.AEnPaperConfig(max_units=0)
