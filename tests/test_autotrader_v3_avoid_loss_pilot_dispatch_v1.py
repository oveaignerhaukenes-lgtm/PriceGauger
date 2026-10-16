"""Dormant close adapter: NO broker POST unless triple operator/server/owner gate."""
from dataclasses import replace
from datetime import datetime,timezone
from types import SimpleNamespace

import pytest

import autotrader_v3_avoid_loss_pilot_dispatch_v1 as pilot
from autotrader_v3_avoid_loss_supervisor_v1 import AvoidLossPilotPlanV1
from autotrader_v3_avoid_loss_v1 import AvoidLossStateV1,ConfirmedPositionV1

NOW=datetime(2026,10,16,20,30,tzinfo=timezone.utc)
P=ConfirmedPositionV1(
    account_id="exact",uic=4912,asset_type="CfdOnIndex",
    position_token="P1",signed_amount=.01,entry_margin_nok=1000,
)
STATE=AvoidLossStateV1(P.key,peak_pct=.0,exit_pending=True,
    exit_reason="LOSS_STOP",last_sample_at=NOW)
PLAN=AvoidLossPilotPlanV1("CLOSE_REQUIRED","LOSS_STOP",STATE,close_needed=True)
INST=SimpleNamespace(
    instance_id="trader1",account_id="exact",uic=4912,
    asset_type="CfdOnIndex",market_name="US Tech 100 NAS",
)


class Broker:
    def __init__(self,*,market=True,activity="id",position_amount=.01):
        self.market=market
        self.activity=activity
        self.amount=position_amount
        self.calls=[]
    def _account_context_exact(self,account_id):
        assert account_id=="exact"
        self.calls.append("context")
        return "account-key","client-key"
    def accounts(self):
        self.calls.append("accounts")
        return [{"AccountId":"exact","Currency":"NOK"}]
    def market_status_exact(self,**kw):
        self.calls.append("market")
        return SimpleNamespace(is_open=self.market,market_state="Open",quote_error=None)
    def positions_exact(self,**kw):
        self.calls.append("positions")
        return [{"PositionId":"P1","PositionBase":{
            "AccountId":"exact","Uic":4912,"AssetType":"CfdOnIndex",
            "Amount":self.amount,"Status":"Open"}}]
    def net_positions_exact(self,**kw):
        self.calls.append("nets")
        return [{"NetPositionBase":{
            "AccountId":"exact","Uic":4912,"AssetType":"CfdOnIndex",
            "AmountLong":.01,"AmountShort":0}}]
    def signed_inventory_exact(self,**kw):
        self.calls.append("inventory")
        return .01
    def precheck(self,order):
        self.calls.append("precheck")
        assert order.buy_sell=="Sell" and order.amount==.01
        assert order.instrument.uic==4912
        return {"PreCheckResult":"Ok"}
    def place_order(self,order,*,confirm_live):
        self.calls.append("POST")
        assert confirm_live
        if self.activity=="timeout":raise TimeoutError("unknown if sent")
        return {"OrderId":"O1"} if self.activity=="id" else {}
    def _post(self,*a,**kw):
        raise AssertionError("Never a second broker order path")


def _set(monkeypatch,*,env=True,guard=None,market=True):
    from autotrader_engine_account_ownership_v1 import ENGINE_V3
    import autotrader_engine_account_ownership_v1 as ownership
    monkeypatch.setattr(ownership,"load_account_owner_v1",
        lambda *a,**kw:SimpleNamespace(engine_id=ENGINE_V3,owner_key="trader1"))
    monkeypatch.setattr(pilot,"load_v3_instances_v1",lambda **kw:(INST,))
    monkeypatch.setattr(pilot,"live_authority_armed_v3",lambda *a,**kw:True)
    monkeypatch.setattr(pilot,"load_confirmed_entry_anchor_v1",lambda **kw:P)
    monkeypatch.setattr(pilot,"pending_order_v3",lambda **kw:guard)
    monkeypatch.setattr(pilot,"order_state_v3",lambda **kw:None)
    monkeypatch.setattr(pilot,"_assert_no_working_orders_v3",lambda *a,**kw:None)
    monkeypatch.setattr(pilot,"save_risk_state_v1",lambda **kw:True)
    ledger=[]
    monkeypatch.setattr(pilot,"reserve_order_v3",lambda **kw:ledger.append(("reserve",kw)) or True)
    monkeypatch.setattr(pilot,"claim_reserved_for_submission_v3",lambda **kw:ledger.append(("claim",kw)) or True)
    monkeypatch.setattr(pilot,"mark_order_v3",lambda **kw:ledger.append(("mark",kw)) or True)
    if env:
        monkeypatch.setenv("PG_AVOID_LOSS_V1_LIVE_PILOT_ENABLE","enabled")
        monkeypatch.setenv("PG_AVOID_LOSS_V1_PILOT_TRADER_ID","trader1")
        monkeypatch.setenv("PG_AVOID_LOSS_V1_PILOT_ACCOUNT_ID","exact")
    else:
        for key in ("PG_AVOID_LOSS_V1_LIVE_PILOT_ENABLE",
                    "PG_AVOID_LOSS_V1_PILOT_TRADER_ID",
                    "PG_AVOID_LOSS_V1_PILOT_ACCOUNT_ID"):
            monkeypatch.delenv(key,raising=False)
    return ledger


def call(b,**kwargs):
    return pilot.dispatch_avoid_loss_close_v1(
        trader_id="trader1",plan=PLAN,broker=b,now=NOW,
        db_path="test.db",**kwargs)


def test_implicit_use_is_inert_and_sends_no_orders(monkeypatch):
    b=Broker()
    assert call(b).status=="LIVE_DISABLED"
    assert not b.calls


def test_env_off_even_with_explicit_approval_never_calls_broker(monkeypatch):
    _set(monkeypatch,env=False)
    b=Broker()
    r=call(b,explicit_pilot_approval=True)
    assert r.status=="LIVE_DISABLED" and not b.calls


@pytest.mark.parametrize("change",[
    {"PG_AVOID_LOSS_V1_PILOT_TRADER_ID":"other"},
    {"PG_AVOID_LOSS_V1_PILOT_ACCOUNT_ID":"other"},
])
def test_exact_env_identity_required(monkeypatch,change):
    _set(monkeypatch)
    for key,val in change.items():monkeypatch.setenv(key,val)
    b=Broker()
    with pytest.raises(pilot.AvoidLossPilotSafetyBlockV1):
        call(b,explicit_pilot_approval=True)
    assert "POST" not in b.calls


def test_market_closed_does_not_reserve_or_post(monkeypatch):
    ledger=_set(monkeypatch)
    b=Broker(market=False)
    outcome=call(b,explicit_pilot_approval=True)
    assert outcome.status=="WAIT_MARKET"
    assert not ledger
    assert "POST" not in b.calls


def test_existing_pending_unknown_never_sends_a_second_close(monkeypatch):
    _set(monkeypatch,guard={"state":"UNKNOWN","request_key":"some-other"})
    b=Broker()
    r=call(b,explicit_pilot_approval=True)
    assert r.status=="WAIT_ORDER" and "POST" not in b.calls


@pytest.mark.parametrize("prior",["RESERVED","SUBMITTING","SUBMITTED","UNKNOWN","RECONCILED","REJECTED"])
def test_any_prior_close_key_blocks_even_if_terminal(monkeypatch,prior):
    _set(monkeypatch)
    monkeypatch.setattr(pilot,"order_state_v3",lambda **kw:prior)
    b=Broker()
    assert call(b,explicit_pilot_approval=True).status=="WAIT_ORDER"
    assert "POST" not in b.calls


def test_inaccurate_broker_inventory_blocks_all_orders(monkeypatch):
    ledger=_set(monkeypatch)
    b=Broker(position_amount=.02)
    with pytest.raises(pilot.AvoidLossPilotSafetyBlockV1):
        call(b,explicit_pilot_approval=True)
    assert not ledger
    assert "POST" not in b.calls


def test_stale_latched_sample_wont_enter_any_broker_path(monkeypatch):
    ledger=_set(monkeypatch)
    b=Broker()
    old=replace(PLAN,next_state=replace(STATE,last_sample_at=NOW.replace(hour=19)))
    with pytest.raises(pilot.AvoidLossPilotSafetyBlockV1):
        pilot.dispatch_avoid_loss_close_v1(
           trader_id="trader1",plan=old,broker=b,now=NOW,
           explicit_pilot_approval=True)
    assert not ledger and not b.calls


def test_full_validated_request_is_submitted_not_claimed_filled(monkeypatch):
    ledger=_set(monkeypatch)
    b=Broker()
    result=call(b,explicit_pilot_approval=True)
    assert result.status=="SUBMITTED"
    assert not result.broker_flat
    assert b.calls.count("POST")==1
    assert [step[0] for step in ledger]==["reserve","claim","mark"]
    assert ledger[-1][1]["state"]=="SUBMITTED"
    assert ledger[0][1]["expected_inventory"]==0.


@pytest.mark.parametrize("activity",["timeout","missing"])
def test_ambiguous_saxo_answer_is_unknown_never_auto_replayed(monkeypatch,activity):
    ledger=_set(monkeypatch)
    b=Broker(activity=activity)
    r=call(b,explicit_pilot_approval=True)
    assert r.status=="UNKNOWN"
    assert b.calls.count("POST")==1
    assert ledger[-1][1]["state"]=="UNKNOWN"
    assert not r.broker_flat


def test_reserved_claim_cas_lost_does_not_place_order(monkeypatch):
    ledger=_set(monkeypatch)
    monkeypatch.setattr(pilot,"claim_reserved_for_submission_v3",lambda **kw:False)
    b=Broker()
    r=call(b,explicit_pilot_approval=True)
    assert r.status=="WAIT_ORDER"
    assert "POST" not in b.calls


def test_pilot_dispatch_is_not_wired_into_existing_live_worker():
    from pathlib import Path
    runtime=Path("autotrader_v3_live_runtime_v1.py").read_text()
    registry=Path("autotrader_v3_strategy_registry_v1.py").read_text()
    assert "dispatch_avoid_loss_close_v1" not in runtime
    assert "autotrader_v3_avoid_loss_pilot_dispatch_v1" not in runtime
    assert "avoid-loss-v1" not in registry
