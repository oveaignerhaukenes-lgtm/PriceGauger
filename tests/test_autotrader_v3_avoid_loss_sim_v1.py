"""Test costed Avoid Loss NAV simulation and strictly causal MACD 2m bars."""
from datetime import datetime,timedelta,timezone
from math import sin
from types import SimpleNamespace
import pytest

from autotrader_v3_avoid_loss_sim_v1 import (
    AvoidLossSimulationConfigV1,run_avoid_loss_sim_v1,_closed_macd_2m,
)

BASE=datetime(2026,10,15,8,0,tzinfo=timezone.utc)


def bars(n=650):
    output=[]
    price=20000.
    for i in range(n):
        # Multiple up/down regimes plus deterministic noise.
        price+=(1.3 if i%190<95 else -1.25)+1.5*sin(i/4)
        open_=price
        close=open_+0.7*sin(i/9)
        output.append(SimpleNamespace(
            bar_time=BASE+timedelta(minutes=i),open=open_,
            high=max(open_,close)+2.5,low=min(open_,close)-2.5,close=close,
        ))
    return output


def test_causal_complete_2m_macd_only():
    x=bars()
    a=_closed_macd_2m([(b.bar_time,b.open,b.high,b.low,b.close) for b in x])
    assert a
    assert all(t.minute%2==0 and t.second==0 for t in a)
    assert all(t>=BASE+timedelta(minutes=60) for t in a)
    b=_closed_macd_2m([
        (bar.bar_time,bar.open,bar.high,bar.low,bar.close)
        for bar in x[:-1]
    ])
    assert list(b) == list(a)[:len(b)]


def test_account_nav_includes_realistic_modelled_roundtrip_costs():
    data=bars(950)
    gross=run_avoid_loss_sim_v1(data,config=AvoidLossSimulationConfigV1(
        commission_bps_per_side=0,full_spread_bps=0,
        slippage_bps_per_side=0,daily_financing_bps=0))
    with_cost=run_avoid_loss_sim_v1(data,config=AvoidLossSimulationConfigV1(
        commission_bps_per_side=2,full_spread_bps=2,
        slippage_bps_per_side=1,daily_financing_bps=1))
    assert gross.completed_minutes==with_cost.completed_minutes==950
    assert len(gross.equity)==950
    assert with_cost.total_costs_nok>=0
    assert all(trade.exit_at>=trade.entry_at for trade in with_cost.trades)
    assert with_cost.final_nav_nok>0
    assert with_cost.net_pct==pytest.approx(
        (with_cost.final_nav_nok/with_cost.initial_nav_nok-1)*100)


def test_holdout_future_does_not_change_past_equity():
    x=bars(1100)
    baseline=run_avoid_loss_sim_v1(x[:900])
    future=x[:900]+[
        SimpleNamespace(**{**b.__dict__,"open":b.open+50,
            "high":b.high+50,"low":b.low+50,"close":b.close+50})
        for b in x[900:]
    ]
    extended=run_avoid_loss_sim_v1(future)
    assert baseline.equity==extended.equity[:900]


def test_flat_for_costly_or_tiny_price_ranges():
    quiet=[]
    for i in range(500):
        quiet.append(SimpleNamespace(bar_time=BASE+timedelta(minutes=i),
            open=100.,high=100.00001,low=99.99999,close=100.))
    s=run_avoid_loss_sim_v1(quiet)
    assert s.final_nav_nok==10000.
    assert not s.trades
    assert s.open_position_direction==0


def test_gaps_are_not_synthetically_filled():
    x=bars(500)
    gapped=x[:200]+x[213:450]
    r=run_avoid_loss_sim_v1(gapped)
    assert r.completed_minutes==437
    assert len(r.equity)==437


def test_invalid_modelled_leverage_and_fees_rejected():
    with pytest.raises(ValueError):
        AvoidLossSimulationConfigV1(margin_per_trade_nok=12000)
    with pytest.raises(ValueError):
        AvoidLossSimulationConfigV1(full_spread_bps=-2)
    with pytest.raises(ValueError):
        run_avoid_loss_sim_v1([])


def test_sim_is_not_broker_code():
    from pathlib import Path
    x=Path("autotrader_v3_avoid_loss_sim_v1.py").read_text()
    for forbidden in ("SaxoOrderRequest","place_order(","run_v3_live_cycle_v1",
                      "configured_live_pilot_client_v3","set_live_authority_v3"):
        assert forbidden not in x



def test_first_entry_minute_adverse_extreme_is_not_ignored(monkeypatch):
    import autotrader_v3_avoid_loss_sim_v1 as model
    data=[]
    for i in range(8):
        data.append(SimpleNamespace(
            bar_time=BASE+timedelta(minutes=i),
            open=100.,close=100.,high=100.5,
            low=90. if i==4 else 99.5))
    monkeypatch.setattr(model,"_closed_macd_2m",
        lambda rows:{
            BASE+timedelta(minutes=2):-0.5,
            BASE+timedelta(minutes=4):+0.5,
        })
    monkeypatch.setattr(model,"evaluate_flat_entry_v1",
        lambda **kwargs:(1,"TEST_ENTER_LONG"))
    out=model.run_avoid_loss_sim_v1(data,config=AvoidLossSimulationConfigV1(
        initial_nav_nok=10000,margin_per_trade_nok=1000,
        notional_per_trade_nok=10000,
        commission_bps_per_side=0,full_spread_bps=0,
        slippage_bps_per_side=0,daily_financing_bps=0))
    assert out.trades
    first=out.trades[0]
    assert first.entry_at==BASE+timedelta(minutes=4)
    assert first.exit_at==first.entry_at
    assert first.reason=="ENTRY_MINUTE_LOSS_STOP"
    assert first.net_pnl_nok==pytest.approx(-10.0)
