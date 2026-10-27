"""Pure V2.3 closed macro + completed 15s micro signal tests (no orders)."""
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
import pytest
import autotrader_v3_macd_stoch_v23_hybrid as hybrid


NOW=datetime(2026,10,27,18,0,tzinfo=timezone.utc)


def bar(seconds_ago, opening, close):
    at=NOW-timedelta(seconds=seconds_ago)
    return SimpleNamespace(
        bar_time=at.isoformat(),
        open=opening,close=close,
        high=max(opening,close),low=min(opening,close),
    )


def test_micro_two_confirmed_15s_with_macro_gate_and_inventory_bounds():
    bars=(bar(60,100.,100.1),bar(45,100.1,100.15),
          bar(30,100.15,100.23),bar(15,100.23,100.32))
    kwargs=dict(bars=bars,macro_side=1,tranche=.01,max_amount=.03,
                now=NOW,latest_spread_bps=1.)
    first=hybrid.micro_target_from_completed_bbo(current_amount=0.,**kwargs)
    assert first[0]==pytest.approx(.01)
    second=hybrid.micro_target_from_completed_bbo(current_amount=.02,**kwargs)
    assert second[0]==pytest.approx(.03)
    flat=hybrid.micro_target_from_completed_bbo(
        current_amount=.02,bars=bars,macro_side=-1,
        tranche=.01,max_amount=.03,now=NOW,latest_spread_bps=1.)
    assert flat[0]==0.
    no_macro=hybrid.micro_target_from_completed_bbo(
        current_amount=.02,bars=bars,macro_side=0,
        tranche=.01,max_amount=.03,now=NOW)
    assert no_macro[0]==0.


def test_micro_stale_data_never_creates_new_position():
    bars=tuple(bar(v+30,100,100.25) for v in (60,45,30,15))
    target,reason=hybrid.micro_target_from_completed_bbo(
        bars=bars,macro_side=1,current_amount=0.,tranche=.01,
        max_amount=.03,now=NOW)
    assert target==0.
    assert reason=="STALE_MICRO"


def test_macro_requires_two_valid_aligned_1m_scores(monkeypatch):
    bars=tuple(SimpleNamespace(
       bar_time=(NOW-timedelta(seconds=60*(90-i))).isoformat(),
       open=100,close=100,high=101,low=99,
    ) for i in range(90))
    observations=(SimpleNamespace(spread=.3),SimpleNamespace(spread=.4))
    monkeypatch.setattr(hybrid,"composite_score_v3",
                        lambda ob,values:(.31,0.,0.))
    side,reason=hybrid.macro_direction_from_closed_1m(
        bars,observations,now=NOW)
    assert side==1
    assert "ALIGNED" in reason
    monkeypatch.setattr(hybrid,"composite_score_v3",
                        lambda ob,values:(.08,0.,0.))
    assert hybrid.macro_direction_from_closed_1m(
        bars,observations,now=NOW)[0]==0
