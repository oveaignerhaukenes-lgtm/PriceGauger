from datetime import datetime,timedelta,timezone
import pytest
from autotrader_impulse_catcher_replay_v1 import ImpulseQuote
from autotrader_ic14_cost_preview_v1 import estimate_costs

T=datetime(2026,11,27,tzinfo=timezone.utc)

def fixture(side):
    s=1 if side=="LONG" else -1
    q=tuple(ImpulseQuote(T+timedelta(seconds=i),100+s*i-1,100+s*i+1) for i in range(20))
    trace=[dict(at=x.at,mid=x.mid,target=side if 2<=i<12 else "FLAT",
                decision="QUALIFIED_IMPULSE_V14" if i==2 else "CONFIRMED_EXIT" if i==12 else None)
           for i,x in enumerate(q)]
    return q,trace

@pytest.mark.parametrize("side",["LONG","SHORT"])
def test_exact_spread_and_delay_decomposition(side):
    q,t=fixture(side)
    # Spread at entry and exit is 2; round trip is 2, not 4.
    r=estimate_costs(q,t,side=side,start=T,end=T+timedelta(seconds=19),delay_s=3,extra_points=.5)
    assert r.signals==r.completed_signals==len(r.trades)==1
    assert r.gross==10 and r.spread==2 and r.delay_drag==0
    assert r.net==7.5 and r.wins==1
    assert r.trades[0].entry_fill==T+timedelta(seconds=5)
    assert r.trades[0].exit_fill==T+timedelta(seconds=15)
    assert r.coverage==1

def test_delay_drag_with_variable_prices_and_spreads():
    q,t=fixture("LONG")
    q=list(q)
    q[5]=ImpulseQuote(q[5].at,108,112)
    q[15]=ImpulseQuote(q[15].at,114,116)
    r=estimate_costs(q,t,side="LONG",start=T,end=q[-1].at,delay_s=3)
    assert r.gross==10 and r.spread==3 and r.delay_drag==5 and r.net==2

def test_gap_and_late_entry_never_credited():
    q,t=fixture("LONG")
    for quotes,delay in ((q[:4]+q[10:],3),(q,10)):
        r=estimate_costs(quotes,t,side="LONG",start=T,end=q[-1].at,delay_s=delay)
        assert r.signals==1 and r.skipped==1 and not r.trades
    r=estimate_costs(q,t[:10],side="LONG",start=T,end=q[9].at)
    assert r.incomplete==1 and not r.trades
    r=estimate_costs(q,t,side="LONG",start=q[3].at,end=q[-1].at)
    assert r.carry_in and not r.trades

def test_zero_delay_explicit_ideal_execution_scenario():
    q,t=fixture("LONG")
    r=estimate_costs(q,t,side="LONG",start=T,end=q[-1].at,delay_s=0)
    assert r.net==8 and r.trades[0].entry_fill==q[2].at
