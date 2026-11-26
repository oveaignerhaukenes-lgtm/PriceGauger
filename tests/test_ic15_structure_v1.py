from datetime import datetime,timedelta,timezone
from math import sin
import pytest
from ic15_structure_v1 import Structure,StructureConfig
from ic15_structure_replay_v1 import compare,MODES
from autotrader_impulse_catcher_replay_v1 import ImpulseQuote
from autotrader_impulse_catcher_v14 import config_v14

T=datetime(2026,11,25,12,tzinfo=timezone.utc)

def quotes(side="LONG"):
    sign=1 if side=="LONG" else -1
    return tuple(ImpulseQuote(T+timedelta(seconds=i),26000+sign*(-.045*min(i,1500)+.06*max(0,i-1500)+7*sin(i/25))-.5,
        26000+sign*(-.045*min(i,1500)+.06*max(0,i-1500)+7*sin(i/25))+.5)
        for i in range(2401))

def trace(q,side):
    m=Structure(StructureConfig(side))
    return [m.update(x.at,x.mid) for x in q]

@pytest.mark.parametrize("side",["LONG","SHORT"])
def test_structural_focus_prefix_causality_and_gap(side):
    q=quotes(side)
    full=trace(q,side)
    assert trace(q[:2100],side)==full[:2100]
    assert all(r["focus"]=="WARMUP" and not r["entry"] for r in full[:1700])
    assert any(r["focus"]!="WARMUP" for r in full[1900:])
    assert any(r["focus"]=="ARMED" for r in full[1900:])
    m=Structure(StructureConfig(side))
    for x in q:m.update(x.at,x.mid)
    gap=m.update(q[-1].at+timedelta(seconds=12),q[-1].mid)
    assert gap["focus"]=="WARMUP" and gap["level"] is None

def test_replay_same_inputs_and_no_early_trade():
    q=quotes()
    r=compare(q,config_v14("LONG"),StructureConfig("LONG"),start=T+timedelta(seconds=1800),delay_s=5.)
    assert tuple(x.mode for x in r)==MODES
    assert all(0<=x.trades<=x.signals and x.drawdown_points>=0 for x in r)
    empty=compare(q,config_v14("LONG"),StructureConfig("LONG"),start=q[-1].at+timedelta(seconds=1))
    assert all(x.signals==x.trades==x.unfinished==0 for x in empty)
    assert compare(q,config_v14("LONG"),StructureConfig("LONG"),start=T+timedelta(seconds=1800),delay_s=5.)==r
    with pytest.raises(ValueError):compare(q[::-1],config_v14("LONG"),StructureConfig("LONG"),start=T)

def test_short_is_directional_mirror():
    a,b=trace(quotes("LONG"),"LONG"),trace(quotes("SHORT"),"SHORT")
    assert [r["focus"] for r in a]==[r["focus"] for r in b]
    assert [r["entry"] for r in a]==[r["entry"] for r in b]
