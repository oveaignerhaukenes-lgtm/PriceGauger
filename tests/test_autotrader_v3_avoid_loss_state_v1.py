"""Durable research ledger: cannot erase or inflate a confirmed broker anchor."""
from datetime import datetime,timedelta,timezone
from dataclasses import replace
import pytest

from autotrader_v3_avoid_loss_v1 import ConfirmedPositionV1,AvoidLossStateV1
from autotrader_v3_avoid_loss_state_v1 import (
    ensure_avoid_loss_research_schema_v1,register_confirmed_entry_anchor_v1,
    load_confirmed_entry_anchor_v1,save_risk_state_v1,load_risk_state_v1,
    retire_confirmed_flat_v1,
)

T0=datetime(2026,10,16,10,0,tzinfo=timezone.utc)
POS=ConfirmedPositionV1("autotrader",4912,"CfdOnIndex","NP-confirmed-1",.01,1200)


def test_anchor_is_immutable_and_idempotent(tmp_path):
    db=str(tmp_path/"risk.db")
    assert load_confirmed_entry_anchor_v1(trader_id="t",db_path=db) is None
    def save(position=POS,request="durable-OPEN",order="SAXO-123"):
        return register_confirmed_entry_anchor_v1(
            trader_id="t",position=position,
            reconciled_open_request_key=request,
            confirmed_order_id=order,
            confirmed_at=T0,db_path=db)
    assert save() is True
    assert save() is False
    assert load_confirmed_entry_anchor_v1(trader_id="t",db_path=db)==POS
    for changed in (replace(POS,entry_margin_nok=100),
                    replace(POS,signed_amount=.02),
                    replace(POS,position_token="different")):
        with pytest.raises(ValueError):
            save(position=changed)
    with pytest.raises(ValueError):
        save(request="other")


def test_peak_and_pending_close_survive_restart_and_never_roll_back(tmp_path):
    db=str(tmp_path/"risk.db")
    register_confirmed_entry_anchor_v1(
        trader_id="p",position=POS,
        reconciled_open_request_key="req-1",
        confirmed_order_id="Saxo-42",
        confirmed_at=T0,db_path=db)
    first=AvoidLossStateV1(POS.key,5.0,True,False,None,T0)
    save_risk_state_v1(trader_id="p",state=first,db_path=db)
    assert load_risk_state_v1(trader_id="p",db_path=db)==first
    pending=replace(first,exit_pending=True,exit_reason="PEAK_GIVEBACK",
                    last_sample_at=T0+timedelta(seconds=2))
    save_risk_state_v1(trader_id="p",state=pending,db_path=db)
    assert load_risk_state_v1(trader_id="p",db_path=db)==pending
    for stale in (first,replace(pending,peak_pct=4.0),
                  replace(pending,exit_pending=False)):
        with pytest.raises(ValueError):
            save_risk_state_v1(trader_id="p",state=stale,db_path=db)
    assert load_risk_state_v1(trader_id="p",db_path=db)==pending


def test_unknown_or_submitted_close_cannot_retire_risk_memory(tmp_path):
    db=str(tmp_path/"risk.db")
    register_confirmed_entry_anchor_v1(
        trader_id="z",position=POS,
        reconciled_open_request_key="req-1",
        confirmed_order_id="Saxo-42",
        confirmed_at=T0,db_path=db)
    state=AvoidLossStateV1(POS.key,2.1,True,True,"LOSS_STOP",T0)
    save_risk_state_v1(trader_id="z",state=state,db_path=db)
    with pytest.raises(ValueError):
        retire_confirmed_flat_v1(
            trader_id="z",broker_exact_flat=False,db_path=db)
    assert load_risk_state_v1(trader_id="z",db_path=db)==state
    assert retire_confirmed_flat_v1(
        trader_id="z",broker_exact_flat=True,db_path=db)
    assert load_risk_state_v1(trader_id="z",db_path=db) is None
    assert load_confirmed_entry_anchor_v1(trader_id="z",db_path=db) is None


def test_risk_state_for_changed_broker_position_rejected(tmp_path):
    db=str(tmp_path/"risk.db")
    register_confirmed_entry_anchor_v1(
        trader_id="z",position=POS,reconciled_open_request_key="req-1",
        confirmed_order_id="Saxo-42",confirmed_at=T0,db_path=db)
    state=AvoidLossStateV1(replace(POS,signed_amount=.02).key,2.0,True)
    with pytest.raises(ValueError):
        save_risk_state_v1(trader_id="z",state=state,db_path=db)
