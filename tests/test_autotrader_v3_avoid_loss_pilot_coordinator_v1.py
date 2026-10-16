"""Broker CLOSE-to-FLAT coordinator must not retire on partial/unknown fills."""
from datetime import datetime,timezone
from types import SimpleNamespace

import pytest

import autotrader_v3_avoid_loss_pilot_coordinator_v1 as mod
from autotrader_v3_avoid_loss_v1 import (
    ConfirmedPositionV1,AvoidLossStateV1,
)
from autotrader_v3_avoid_loss_supervisor_v1 import AvoidLossPilotPlanV1
from autotrader_v3_avoid_loss_state_v1 import (
    register_confirmed_entry_anchor_v1,
    load_confirmed_entry_anchor_v1,
    load_avoid_loss_exit_bar_v1,
    load_risk_state_v1,
)
from autotrader_v3_order_guard_v1 import reserve,mark

NOW=datetime(2026,10,19,8,0,tzinfo=timezone.utc)
POSITION=ConfirmedPositionV1(
    account_id="acct",uic=4912,asset_type="CfdOnIndex",
    position_token="P1",signed_amount=.01,entry_margin_nok=800,
)
STATE=AvoidLossStateV1(POSITION.key,peak_pct=3.2,
    trailing_armed=True,exit_pending=True,exit_reason="PEAK_GIVEBACK",
    last_sample_at=NOW)


class Broker:
    def __init__(self,*,kind="confirmed",open_position=False):
        self.kind=kind
        self.open_position=open_position
        self.calls=[]
    def _account_context_exact(self,account_id):
        assert account_id=="acct"
        return "key","client"
    def accounts(self):
        return [{"AccountId":"acct","Currency":"NOK"}]
    def net_positions_exact(self,**kw):
        self.calls.append("net")
        assert kw=={"account_id":"acct","uic":4912,"asset_type":"CfdOnIndex"}
        if self.open_position:
            return ({"NetPositionBase":{
                "AccountId":"acct","Uic":4912,"AssetType":"CfdOnIndex",
                "AmountLong":.01}},)
        return ()
    def positions_exact(self,**kw):
        self.calls.append("individual")
        if self.open_position:
            return ({"PositionId":"P1","PositionBase":{
                "AccountId":"acct","Uic":4912,"AssetType":"CfdOnIndex",
                "Amount":.01}},)
        return ()
    def order_activity_exact(self,**kw):
        self.calls.append("audit")
        assert kw["order_id"]=="O1"
        return {"available":True,
                "status":"FinalFill" if self.kind=="confirmed" else "Fill",
                "sub_status":"Confirmed",
                "position_id":"P1","side":"Sell","filled_amount":.01}
    def place_order(self,*a,**kw):
        raise AssertionError("reconciliation never places orders")
    def _post(self,*a,**kw):
        raise AssertionError("reconciliation never POSTs")


def prep(tmp_path,monkeypatch,*,order_state="RECONCILED"):
    from autotrader_v3_avoid_loss_pilot_dispatch_v1 import close_intent_key_v1
    import autotrader_v3_instance_registry_v1 as registry
    monkeypatch.setattr(registry,"load_v3_instances_v1",
        lambda **kw:(SimpleNamespace(instance_id="trader",account_id="acct",
            uic=4912,asset_type="CfdOnIndex"),))
    monkeypatch.setattr(mod,"_assert_no_working_orders_v3",lambda *a,**kw:None)
    db=str(tmp_path/"lifecycle.sqlite")
    register_confirmed_entry_anchor_v1(
        trader_id="trader",position=POSITION,
        reconciled_open_request_key="R-OPEN",confirmed_order_id="O-OPEN",
        confirmed_at=NOW,db_path=db)
    plan=AvoidLossPilotPlanV1("CLOSE_REQUIRED","PEAK_GIVEBACK",STATE,close_needed=True)
    mod.persist_avoid_loss_plan_v1(trader_id="trader",plan=plan,db_path=db)
    key=close_intent_key_v1(trader_id="trader",position_token="P1",signed_amount=.01)
    reserve(request_key=key,trader_id="trader",account_id="acct",
        uic=4912,asset_type="CfdOnIndex",expected_inventory=0,
        submitted_amount=.01,submitted_side="Sell",db_path=db)
    mark(request_key=key,state=order_state,broker_order_id="O1",db_path=db)
    return db


def test_final_full_fill_and_three_exact_flat_reads_retires_after_exit_bar(monkeypatch,tmp_path):
    db=prep(tmp_path,monkeypatch)
    b=Broker()
    r=mod.reconcile_avoid_loss_close_v1(trader_id="trader",broker=b,now=NOW,db_path=db)
    assert r.status=="BROKER_FLAT_VERIFIED" and r.position_retired
    assert b.calls==["net","individual","net","individual","audit","net","individual"]
    assert load_confirmed_entry_anchor_v1(trader_id="trader",db_path=db) is None
    assert load_avoid_loss_exit_bar_v1(trader_id="trader",db_path=db)==NOW


def test_partial_fill_does_not_retire_anchor_or_latch(monkeypatch,tmp_path):
    db=prep(tmp_path,monkeypatch)
    r=mod.reconcile_avoid_loss_close_v1(
        trader_id="trader",broker=Broker(kind="partial"),now=NOW,db_path=db)
    assert not r.position_retired
    assert r.status=="UNPROTECTED"
    assert load_confirmed_entry_anchor_v1(trader_id="trader",db_path=db)==POSITION
    assert load_risk_state_v1(trader_id="trader",db_path=db).exit_pending


def test_any_open_individual_position_prevents_retirement(monkeypatch,tmp_path):
    db=prep(tmp_path,monkeypatch)
    r=mod.reconcile_avoid_loss_close_v1(
        trader_id="trader",broker=Broker(open_position=True),now=NOW,db_path=db)
    assert not r.position_retired
    assert load_confirmed_entry_anchor_v1(trader_id="trader",db_path=db) is not None


@pytest.mark.parametrize("state",["RESERVED","SUBMITTING","SUBMITTED","UNKNOWN","REJECTED"])
def test_unreconciled_or_unknown_order_keeps_immutable_anchor(monkeypatch,tmp_path,state):
    db=prep(tmp_path,monkeypatch,order_state=state)
    b=Broker()
    r=mod.reconcile_avoid_loss_close_v1(trader_id="trader",broker=b,now=NOW,db_path=db)
    assert r.status=="WAIT_ORDER"
    assert load_confirmed_entry_anchor_v1(trader_id="trader",db_path=db) is not None
    assert not b.calls


def test_no_ever_submitting_saxo_from_coordinator_and_sticky_stop_save(monkeypatch,tmp_path):
    db=prep(tmp_path,monkeypatch)
    assert load_risk_state_v1(trader_id="trader",db_path=db).peak_pct==3.2
    plan=AvoidLossPilotPlanV1("WAIT_MARKET","MARKET_CLOSED",STATE)
    with pytest.raises(ValueError):
        mod.persist_avoid_loss_plan_v1(trader_id="trader",plan=plan,db_path=db)
    assert load_risk_state_v1(trader_id="trader",db_path=db).exit_pending


def test_missing_broker_cannot_retire_even_after_reconciled_close(monkeypatch,tmp_path):
    db=prep(tmp_path,monkeypatch)
    r=mod.reconcile_avoid_loss_close_v1(trader_id="trader",broker=None,now=NOW,db_path=db)
    assert r.status=="BLOCKED"
    assert load_confirmed_entry_anchor_v1(trader_id="trader",db_path=db) is not None
