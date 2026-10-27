"""Opt-in V3 LIVE risk overlays; deterministic evidence and broker-safe boundaries."""
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace

import pytest

from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_protective_live_v1 import (
    ProtectiveEvidenceV3,ProtectiveModifierV3,impulse_evidence_v3,
    drawdown_evidence_v3,evaluate_account_loss_live_v3,
    evaluate_impulse_live_v3,reset_account_loss_lock_v3,
)
from autotrader_v3_modifier_audit_v1 import (
    load_modifier_live_events_v3,record_modifier_selection_changes_v3,
    sorted_modifiers_by_last_change_v3,record_modifier_evaluation_v3,
    record_modifier_target_change_v3,
)

NOW=datetime(2026,10,27,12,0,tzinfo=timezone.utc)


def quotes(*,shock=False,gap=False):
    rows=[]
    for i in range(81):
        if gap and i>55:continue
        stamp=NOW-timedelta(seconds=80-i)
        mid=20000.
        if shock and i>=71:
            mid-=3.0*(i-70)  # -15bp adverse impulse
        rows.append({
            "quote_at":stamp.isoformat(),
            "received_at":(stamp+timedelta(milliseconds=200)).isoformat()
              if i<80 else stamp.isoformat(),
            "bid":mid-1.0,"ask":mid+1.0,
        })
    return rows


def test_adverse_10s_move_for_long_forces_flat_and_blocks_future_reentry():
    signal,_=impulse_evidence_v3(
        rows=quotes(shock=True),now=NOW,actual_amount=.02)
    assert signal.status=="IMPULSE_PAUSE"
    assert signal.threshold_bps>=9
    mod=ProtectiveModifierV3("impulse-exit",signal,.02)
    target,_=mod.apply(None,TargetInventoryV3(.03))
    assert target.amount==0
    # Pause remains flat even after Saxo reconciles old LONG to zero.
    target,_=ProtectiveModifierV3("impulse-exit",signal,0.).apply(
        None,TargetInventoryV3(.01))
    assert target.amount==0


def test_favorable_impulse_does_not_exit_and_quiet_time_controls_resume():
    signal,_=impulse_evidence_v3(
        rows=quotes(shock=True),now=NOW,actual_amount=-.02)
    assert signal.status=="CLEAR"
    before,_=impulse_evidence_v3(
        rows=quotes(),now=NOW,actual_amount=0,was_paused=True)
    assert before.status=="IMPULSE_PAUSE"
    after,_=impulse_evidence_v3(
        rows=quotes(),now=NOW,actual_amount=0,was_paused=True,
        quiet_since=NOW-timedelta(seconds=30))
    assert after.status=="CLEAR"


def test_invalid_or_stale_data_never_authorizes_a_new_trade():
    evidence,_=impulse_evidence_v3(
        rows=quotes(gap=True),now=NOW,actual_amount=.02)
    assert evidence.status=="DATA_MISSING"
    mod=ProtectiveModifierV3("impulse-exit",evidence,.02)
    target,_=mod.apply(None,TargetInventoryV3(.03))
    assert target.amount==pytest.approx(.02)
    target,_=mod.apply(None,TargetInventoryV3(0))
    assert target.amount==0
    assert impulse_evidence_v3(rows=quotes()[:-1]+quotes()[-1:],
        now=NOW,actual_amount=.01)[0].status=="CLEAR"


def test_saxo_exact_account_nav_drawdown_and_lock_cannot_trade_around():
    assert drawdown_evidence_v3(total_value=95,verified=True,
                                peak_value=100).status=="DRAWDOWN_WARN"
    assert drawdown_evidence_v3(total_value=92,verified=True,
                                peak_value=100).status=="DRAWDOWN_NO_ADD"
    lock=drawdown_evidence_v3(total_value=89,verified=True,peak_value=100)
    assert lock.status=="DRAWDOWN_LOCK"
    assert ProtectiveModifierV3("account-loss-lock",lock,-.04).apply(
        None,TargetInventoryV3(-.02))[0].amount==0
    assert drawdown_evidence_v3(total_value=100,verified=True,
        peak_value=100,locked=True).status=="DRAWDOWN_LOCK"
    assert drawdown_evidence_v3(total_value=None,verified=False,
        peak_value=100).status=="DATA_MISSING"


class FakeSaxo:
    def __init__(self):self.total=100.;self.actual=0.
    def accounts(self):
        return ({"AccountId":"A1","AccountKey":"KEY1","ClientKey":"CK1",
                 "Currency":"NOK","AccountName":"test"},)
    @property
    def client(self):return self
    def _get(self,path,params):
        assert path=="port/v1/balances"
        assert params=={"AccountKey":"KEY1","ClientKey":"CK1"}
        return {"Currency":"NOK","TotalValue":self.total,"CalculationReliability":"Ok"}
    def signed_inventory_exact(self,**kwargs):
        assert kwargs["account_id"]=="A1" and kwargs["uic"]==4912
        return self.actual


def test_durable_latch_persists_after_nav_rebound_requires_manual_flat_reset(tmp_path):
    db=str(tmp_path/"risk.db")
    broker=FakeSaxo();account=broker.accounts()[0]
    args=dict(trader_id="A",context="A1|4912|CfdOnIndex|NOK",
              account=account,broker=broker,now=NOW,db_path=db)
    assert evaluate_account_loss_live_v3(**args).status=="CLEAR"
    broker.total=89.
    assert evaluate_account_loss_live_v3(
        **{**args,"now":NOW+timedelta(minutes=1)}).status=="DRAWDOWN_LOCK"
    broker.total=120.
    assert evaluate_account_loss_live_v3(
        **{**args,"now":NOW+timedelta(minutes=2)}).status=="DRAWDOWN_LOCK"
    broker.actual=.01
    with pytest.raises(ValueError,match="FLAT"):
        reset_account_loss_lock_v3(
            trader_id="A",context=args["context"],account_id="A1",uic=4912,
            asset_type="CfdOnIndex",broker=broker,now=NOW,db_path=db)
    broker.actual=0.
    assert reset_account_loss_lock_v3(
        trader_id="A",context=args["context"],account_id="A1",uic=4912,
        asset_type="CfdOnIndex",broker=broker,now=NOW,db_path=db)==120.
    assert evaluate_account_loss_live_v3(
        **{**args,"now":NOW+timedelta(minutes=3)}).status=="CLEAR"


def test_active_quote_guard_is_durable_and_context_scoped(tmp_path):
    db=str(tmp_path/"quotes.db")
    from database import connect
    with connect(db) as con:
        con.execute("""CREATE TABLE lsim_hyper_quotes_1s(
            provider_uic INTEGER NOT NULL,quote_at TEXT NOT NULL,
            received_at TEXT NOT NULL,bid REAL NOT NULL,ask REAL NOT NULL)""")
        for q in quotes(shock=True):
            con.execute("""INSERT INTO lsim_hyper_quotes_1s
                (provider_uic,quote_at,received_at,bid,ask)
                VALUES(?,?,?,?,?)""",(4912,q["quote_at"],q["received_at"],q["bid"],q["ask"]))
    args=dict(trader_id="A",context="A1|4912|CfdOnIndex|NOK",uic=4912,
              actual_amount=.01,now=NOW,db_path=db)
    assert evaluate_impulse_live_v3(**args).status=="IMPULSE_PAUSE"
    with connect(db) as con:
        con.execute("DELETE FROM lsim_hyper_quotes_1s")
    assert evaluate_impulse_live_v3(**{
        **args,"actual_amount":0.,"now":NOW+timedelta(seconds=12)
    }).status=="IMPULSE_PAUSE"


def test_event_channel_orders_last_saved_first_and_idempotent_targets(tmp_path):
    db=str(tmp_path/"events.db")
    items=[SimpleNamespace(key=s) for s in ("old","new","third")]
    record_modifier_selection_changes_v3(
        trader_id="A",before=(),after=("old",),db_path=db,
        at="2026-10-27T01:00:00+00:00")
    record_modifier_selection_changes_v3(
        trader_id="A",before=("old",),after=("old","third"),db_path=db,
        at="2026-10-27T01:02:00+00:00")
    ordered=sorted_modifiers_by_last_change_v3("A",items,db_path=db)
    assert [v.key for v in ordered]==["third","old","new"]
    assert record_modifier_evaluation_v3(
        trader_id="A",modifier_key="third",status="IMPULSE_PAUSE",
        detail="FLAT requested, not confirmed",now=NOW,db_path=db)
    assert not record_modifier_evaluation_v3(
        trader_id="A",modifier_key="third",status="IMPULSE_PAUSE",
        detail="same",now=NOW,db_path=db)
    assert record_modifier_target_change_v3(
        trader_id="A",modifier_key="third",decision_key="pulse:1",
        before_amount=.02,after_amount=0.,now=NOW,db_path=db)
    assert not record_modifier_target_change_v3(
        trader_id="A",modifier_key="third",decision_key="pulse:1",
        before_amount=.02,after_amount=0.,now=NOW,db_path=db)
    events=load_modifier_live_events_v3(
        trader_id="A",modifier_key="third",db_path=db)
    assert any(x["status"]=="FLAT" and "not yet" in x["detail"] for x in events)
