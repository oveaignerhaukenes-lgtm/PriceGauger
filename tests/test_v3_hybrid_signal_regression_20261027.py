"""V2.3 pure closed 15s signal regression."""
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
import pytest
from autotrader_v3_macd_stoch_v23_hybrid import (
    micro_target_from_completed_bbo,macro_direction_from_closed_1m,
)
NOW=datetime(2026,10,27,18,0,tzinfo=timezone.utc)


def bar(offset,op,cl):
    return SimpleNamespace(bar_time=(NOW-timedelta(seconds=offset)).isoformat(),
                           open=op,close=cl,high=max(op,cl),low=min(op,cl))


def test_micro_two_consecutive_completed_green_bars_and_max_inventory():
    bars=(bar(60,100.,100.1),bar(45,100.1,100.15),
          bar(30,100.15,100.23),bar(15,100.23,100.32))
    options=dict(bars=bars,macro_side=1,tranche=.01,max_amount=.03,
                 now=NOW,latest_spread_bps=1.)
    first=micro_target_from_completed_bbo(current_amount=0.,**options)
    assert first[0]==pytest.approx(.01)
    build=micro_target_from_completed_bbo(current_amount=.02,**options)
    assert build[0]==pytest.approx(.03)
    opposite=micro_target_from_completed_bbo(
        bars=bars,macro_side=-1,current_amount=.02,
        tranche=.01,max_amount=.03,now=NOW)
    assert opposite[0]==0.


def test_micro_never_opens_on_stale_bars():
    bars=tuple(bar(sec+30,100.,100.3) for sec in (60,45,30,15))
    wanted,why=micro_target_from_completed_bbo(
        bars=bars,macro_side=1,current_amount=0.,
        tranche=.01,max_amount=.03,now=NOW)
    assert wanted==0.
    assert why=="STALE_MICRO"


def test_macro_two_confirmed_one_minute_composites(monkeypatch):
    import autotrader_v3_macd_stoch_v23_hybrid as hybrid
    bars=tuple(bar(60*(90-i),99.,100.) for i in range(90))
    obs=(SimpleNamespace(spread=.3),SimpleNamespace(spread=.4))
    monkeypatch.setattr(hybrid,"composite_score_v3",
                        lambda *a:(.31,0.,0.))
    side,why=macro_direction_from_closed_1m(bars,obs,now=NOW)
    assert side==1
    monkeypatch.setattr(hybrid,"composite_score_v3",
                        lambda *a:(.05,0.,0.))
    assert macro_direction_from_closed_1m(bars,obs,now=NOW)[0]==0
