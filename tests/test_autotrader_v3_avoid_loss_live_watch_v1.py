"""Saxo LIVE Avoid Loss watch: exact margin-to-PositionId and sticky risk CLOSE."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import autotrader_v3_avoid_loss_live_v1 as live
from autotrader_v3_avoid_loss_state_v1 import (
    load_risk_state_v1,load_confirmed_entry_anchor_v1,
    load_avoid_loss_exit_bar_v1,
)

NOW=datetime(2026,10,16,9,0,tzinfo=timezone.utc)
ENROLLMENT=SimpleNamespace(
    pilot_key="pilot-avoid-loss",account_id="NOK-ACCT",
    uic=4912,asset_type="CfdOnIndex",strategy_key="avoid-loss-v1",
)
BASE={
    "AccountId":"NOK-ACCT","Uic":4912,"AssetType":"CfdOnIndex",
    "Amount":.01,"Status":"Open",  # documented PositionStatic omits OpeningDirection
}


class SaxoFake:
    def __init__(self):
        self.amount=.01
        self.pnl_nok=30.
        self.costs_nok=10.
        self.quote_as_of=NOW
        self.currency="NOK"
        self.position_id="POSITION-123"
        self.extra=False
        self.history_status="FinalFill"
        self.history_substatus="Confirmed"
        self.audit_position_id="POSITION-123"
        self.audit_reads=0

    def accounts(self):
        return ({"AccountId":"NOK-ACCT","Currency":self.currency},)
    def signed_inventory_exact(self,**kwargs):
        return self.amount
    def positions_exact(self,**kwargs):
        if self.amount==0:return ()
        base={**BASE,"Amount":abs(self.amount)}
        row={"PositionId":self.position_id,"PositionBase":base,
             "PositionView":{
                "ProfitLossOnTradeInBaseCurrency":self.pnl_nok,
                "TradeCostsTotalInBaseCurrency":self.costs_nok,
                "CurrentPriceLastTraded":self.quote_as_of.isoformat(),
                "CurrentPriceDelayMinutes":0,
                "CalculationReliability":"Ok",
            }}
        if self.extra:return (row,row)
        return (row,)
    def order_activity_exact(self,**kwargs):
        self.audit_reads+=1
        return {"available":True,"status":self.history_status,
                "sub_status":self.history_substatus,
                "position_id":self.audit_position_id,
                "filled_amount":.01,"side":"Buy"}


def setup_watch(monkeypatch,broker,db):
    monkeypatch.setattr(live,"active_avoid_loss_traders_v1",
                        lambda **kwargs:(ENROLLMENT,))
    monkeypatch.setattr(live,"configured_live_pilot_client_v3",
                        lambda :broker)
    monkeypatch.setattr(live,"pending_order_v3",lambda **kwargs:None)
    monkeypatch.setattr(live,"staged_entry_for_reconciled_order_v1",
        lambda **kwargs:{"request_key":"OPEN-123","initial_margin_nok":1000.,
                         "signed_amount":.01,"submitted_side":"Buy",
                         "submitted_amount":.01,"expected_inventory":.01,
                         "broker_order_id":"SAXO-42"})
    align=[]
    monkeypatch.setattr(live,"align_closed_bar_target_v3",
                        lambda **kwargs:align.append(kwargs) or True)
    return align


def test_confirmed_broker_entry_arm_peak_stop_latch_and_flat_restart(monkeypatch,tmp_path):
    broker=SaxoFake();db=str(tmp_path/"risk.db")
    calls=setup_watch(monkeypatch,broker,db)
    assert live.run_avoid_loss_live_risk_once(db_path=db,now=NOW)==()
    anchored=load_confirmed_entry_anchor_v1(trader_id=ENROLLMENT.pilot_key,db_path=db)
    assert anchored.position_token=="POSITION-123"
    assert anchored.entry_margin_nok==1000
    assert broker.audit_reads==1
    saved=load_risk_state_v1(trader_id=ENROLLMENT.pilot_key,db_path=db)
    assert saved.trailing_armed and saved.peak_pct==pytest.approx(2.0)
    broker.pnl_nok=27 # net +17 => below 1.8% high-water floor
    breach=live.run_avoid_loss_live_risk_once(
        db_path=db,now=NOW+timedelta(seconds=1))
    assert breach==(ENROLLMENT.pilot_key,)
    assert calls and calls[-1]["target_amount"]==0
    latched=load_risk_state_v1(trader_id=ENROLLMENT.pilot_key,db_path=db)
    assert latched.exit_pending and latched.exit_reason=="PEAK_GIVEBACK"
    broker.pnl_nok=50
    # Gain recovers, but cannot re-open or cancel unconfirmed CLOSE.
    assert live.run_avoid_loss_live_risk_once(
        db_path=db,now=NOW+timedelta(seconds=2))==(ENROLLMENT.pilot_key,)
    assert load_risk_state_v1(trader_id=ENROLLMENT.pilot_key,db_path=db).exit_pending
    broker.amount=0
    assert live.run_avoid_loss_live_risk_once(
        db_path=db,now=NOW+timedelta(seconds=3))==()
    assert load_confirmed_entry_anchor_v1(trader_id=ENROLLMENT.pilot_key,db_path=db) is None
    assert load_avoid_loss_exit_bar_v1(trader_id=ENROLLMENT.pilot_key,db_path=db)==NOW+timedelta(seconds=3)


def test_initial_minus_one_percent_requests_flat(monkeypatch,tmp_path):
    broker=SaxoFake();broker.pnl_nok=0;broker.costs_nok=10
    db=str(tmp_path/"neg.db");calls=setup_watch(monkeypatch,broker,db)
    assert live.run_avoid_loss_live_risk_once(
        db_path=db,now=NOW)==(ENROLLMENT.pilot_key,)
    assert calls[-1]["target_amount"]==0
    assert load_risk_state_v1(trader_id=ENROLLMENT.pilot_key,
                              db_path=db).exit_reason=="LOSS_STOP"


@pytest.mark.parametrize("change",[
    "wrong_currency","two_positions","wrong_order_status","stale_quote",
    "partial_fill","wrong_position_id","unconfirmed_fill",
])
def test_no_false_protection_with_unverifiable_saxo(monkeypatch,tmp_path,change):
    broker=SaxoFake();db=str(tmp_path/f"{change}.db")
    if change=="wrong_currency":broker.currency="USD"
    if change=="two_positions":broker.extra=True
    if change=="wrong_order_status":broker.history_status="Unknown"
    if change=="stale_quote":broker.quote_as_of=NOW-timedelta(minutes=1)
    if change=="partial_fill":broker.history_status="Fill"
    if change=="wrong_position_id":broker.audit_position_id="ANOTHER-POSITION"
    if change=="unconfirmed_fill":broker.history_substatus="Rejected"
    calls=setup_watch(monkeypatch,broker,db)
    assert live.run_avoid_loss_live_risk_once(db_path=db,now=NOW)==()
    assert calls==[]
    from database import connect
    with connect(db,force_sqlite=True) as con:
        row=con.execute("SELECT status FROM autotrader_v3_avoid_loss_monitor_v1"
                        " WHERE trader_id=?",(ENROLLMENT.pilot_key,)).fetchone()
    assert row["status"]=="UNPROTECTED"


def test_safe_wiring_full_order_path_and_no_direct_broker_post():
    source=Path("autotrader_v3_avoid_loss_live_v1.py").read_text()
    assert "broker.place_order(" not in source
    assert "reserve_order_v3(" not in source
    worker=Path("worker.py").read_text()
    assert "run_avoid_loss_live_risk_once(" in worker
    assert "only_trader_ids=need_cycle" in worker
    runtime=Path("autotrader_v3_live_runtime_v1.py").read_text()
    for evidence in (
        "precheck_margin_nok_v1(","stage_entry_preflight_v1(",
        "risk_state.exit_pending","MacdTrailingDecisionV3(",
        "plan_execution_v3(snapshot)","reserve_order_v3(",
        "claim_reserved_for_submission_v3(","mark_order_v3(",
        "broker.place_order(","cost_assessment is None or cost_assessment.blocked:",
    ):
        assert evidence in runtime
