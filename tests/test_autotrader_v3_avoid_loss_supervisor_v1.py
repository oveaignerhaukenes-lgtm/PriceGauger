"""Unarmed Avoid Loss state machine: restart, weekend, partial fill and outage."""
from datetime import datetime, timedelta, timezone
from dataclasses import replace

import pytest

from autotrader_v3_avoid_loss_supervisor_v1 import plan_avoid_loss_pilot_v1
from autotrader_v3_avoid_loss_v1 import (
    BrokerPnLSampleV1, ConfirmedPositionV1, AvoidLossStateV1,
)

T=datetime(2026,10,16,21,30,tzinfo=timezone.utc)
POSITION=ConfirmedPositionV1(
    account_id="acct",uic=4912,asset_type="CfdOnIndex",
    position_token="SAXO-1",signed_amount=.01,entry_margin_nok=1000,
)


def evidence(position=POSITION):
    b={"AccountId":position.account_id,"Uic":position.uic,
       "AssetType":position.asset_type,"Amount":abs(position.signed_amount),
       "Status":"Open"}
    nb={"AccountId":position.account_id,"Uic":position.uic,
        "AssetType":position.asset_type,
        "AmountLong":abs(position.signed_amount) if position.signed_amount>0 else 0,
        "AmountShort":abs(position.signed_amount) if position.signed_amount<0 else 0}
    return ([{"NetPositionBase":nb}],
            [{"PositionId":position.position_token,"PositionBase":b}])


def sample(pnl,*,when=T,position=POSITION):
    return BrokerPnLSampleV1(
        position_key=position.key,
        mark_to_liquidate_nok=pnl,currency="NOK",
        as_of=when,reliability="Ok",quote_delay_minutes=0,
        has_verified_costs=True,
    )


def plan(pnl=None,**changes):
    net,ind=evidence()
    kwargs={
        "position":POSITION,"state":None,
        "sample":None if pnl is None else sample(pnl),
        "exact_net_rows":net,"exact_individual_rows":ind,
        "no_broker_working_orders":True,
        "durable_order_state":None,"market_is_open":True,
        "now":T,
    }
    kwargs.update(changes)
    return plan_avoid_loss_pilot_v1(**kwargs)


def test_one_percent_loss_sets_sticky_close_demand_without_saxo_order():
    decision=plan(-10)
    assert decision.status=="CLOSE_REQUIRED"
    assert decision.close_needed and decision.next_state.exit_pending
    assert decision.next_state.exit_reason=="LOSS_STOP"
    assert decision.pnl_pct==-1.0


def test_two_percent_arms_trailing_and_ten_percent_peak_giveback_triggers_close():
    first=plan(20)
    assert first.status=="MONITORING"
    assert first.next_state.trailing_armed
    assert first.next_state.peak_pct==2
    high=plan(50,state=first.next_state,sample=sample(50,when=T+timedelta(seconds=1)),
              now=T+timedelta(seconds=1))
    assert high.next_state.peak_pct==5
    trigger=plan(44,state=high.next_state,sample=sample(44,when=T+timedelta(seconds=2)),
                 now=T+timedelta(seconds=2))
    assert trigger.status=="CLOSE_REQUIRED"
    assert trigger.next_state.exit_reason=="PEAK_GIVEBACK"
    assert trigger.pnl_pct==4.4


def test_pending_close_survives_weekend_then_signals_once_market_reopens():
    stopped=plan(-10).next_state
    closed=plan(state=stopped,market_is_open=False)
    assert closed.status=="WAIT_MARKET"
    assert closed.next_state is stopped and stopped.exit_pending
    # Monday: fresh evidence; same persisted stop plan is still required.
    monday=T+timedelta(days=3)
    reopened=plan(state=stopped,now=monday,sample=sample(4,when=monday),
                  market_is_open=True)
    assert reopened.status=="CLOSE_REQUIRED"
    assert reopened.next_state.exit_pending
    assert reopened.close_needed


@pytest.mark.parametrize("order",["RESERVED","SUBMITTING","SUBMITTED","UNKNOWN"])
def test_unresolved_order_is_wait_never_second_close(order):
    stopped=plan(-10).next_state
    decision=plan(state=stopped,durable_order_state=order,sample=sample(-11))
    assert decision.status=="WAIT_ORDER"
    assert not decision.close_needed


@pytest.mark.parametrize("order",["RECONCILED","REJECTED"])
def test_terminal_close_with_inventory_remaining_is_not_auto_retried(order):
    stopped=plan(-10).next_state
    decision=plan(state=stopped,durable_order_state=order,sample=sample(-11))
    assert decision.status=="UNPROTECTED"
    assert not decision.close_needed


def test_closed_market_held_flat_is_not_interpreted_as_stop_execution():
    r=plan(0,market_is_open=False)
    assert r.status=="WAIT_MARKET"
    assert not r.broker_flat_confirmed and not r.close_needed


def test_open_position_without_anchor_cannot_be_adopted():
    r=plan(10,position=None)
    assert r.status=="UNPROTECTED"
    assert r.reason=="OPEN_POSITION_HAS_NO_CONFIRMED_ANCHOR"


@pytest.mark.parametrize("mismatch",["qty","position_id","account","status","hedge"])
def test_broker_exact_position_mismatch_is_unprotected(mismatch):
    net,ind=evidence()
    if mismatch=="qty":ind[0]["PositionBase"]["Amount"]=.02
    if mismatch=="position_id":ind[0]["PositionId"]="not-anchored"
    if mismatch=="account":ind[0]["PositionBase"]["AccountId"]="other"
    if mismatch=="status":ind[0]["PositionBase"]["Status"]="Closed"
    if mismatch=="hedge":net[0]["NetPositionBase"].update(AmountLong=.02,AmountShort=.01)
    r=plan(5,exact_net_rows=net,exact_individual_rows=ind)
    assert r.status=="UNPROTECTED"


def test_pnl_timeout_missing_or_stale_does_not_erase_stop_latch():
    state=plan(-10).next_state
    missing=plan(state=state,sample=None)
    assert missing.status=="UNPROTECTED" and missing.next_state==state
    stale=plan(state=state,sample=sample(-15,when=T-timedelta(seconds=12)))
    assert stale.status=="UNPROTECTED" and stale.next_state==state


def test_after_confirmed_final_close_both_broker_sources_must_be_empty():
    state=plan(-10).next_state
    base={"position":POSITION,"state":state,"sample":None,
          "exact_net_rows":[],"exact_individual_rows":[],
          "no_broker_working_orders":True,"durable_order_state":"RECONCILED",
          "confirmed_close_fill":True,"market_is_open":False,"now":T}
    done=plan_avoid_loss_pilot_v1(**base)
    assert done.broker_flat_confirmed
    assert done.status=="BROKER_FLAT_VERIFIED"
    for patch in (
        {"exact_net_rows":evidence()[0]},
        {"exact_individual_rows":evidence()[1]},
        {"confirmed_close_fill":False},
        {"no_broker_working_orders":None},
        {"durable_order_state":"SUBMITTED"},
        {"durable_order_state":None},
        {"state":None},
    ):
        r=plan_avoid_loss_pilot_v1(**{**base,**patch})
        assert not r.broker_flat_confirmed


@pytest.mark.parametrize("state",["RESERVED","SUBMITTING","SUBMITTED","UNKNOWN"])
def test_flat_but_order_unresolved_does_not_retire_margin(state):
    r=plan(position=POSITION,exact_net_rows=[],exact_individual_rows=[],
           durable_order_state=state)
    assert r.status=="WAIT_ORDER"
    assert not r.broker_flat_confirmed


def test_unknown_market_quote_or_active_orders_is_not_executable():
    assert not plan(-10,market_is_open=None).close_needed
    assert not plan(-10,no_broker_working_orders=None).close_needed
    assert not plan(-10,no_broker_working_orders=False).close_needed


def test_signed_short_exact_inventory_and_stop():
    short=ConfirmedPositionV1(account_id="acct",uic=4912,asset_type="CfdOnIndex",
                             position_token="short",signed_amount=-.01,
                             entry_margin_nok=1000)
    net,ind=evidence(short)
    r=plan_avoid_loss_pilot_v1(position=short,state=None,sample=sample(-10,position=short),
        exact_net_rows=net,exact_individual_rows=ind,no_broker_working_orders=True,
        durable_order_state=None,market_is_open=True,now=T)
    assert r.close_needed and r.next_state.exit_reason=="LOSS_STOP"
