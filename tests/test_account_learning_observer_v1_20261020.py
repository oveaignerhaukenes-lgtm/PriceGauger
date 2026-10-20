"""Account learning v1: account isolation, causality, no profit invention."""
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import pytest

from database import connect
from autotrader_saxo_account_truth_v1 import SaxoAccountTruthV1,save_account_truth_v1
from autotrader_account_learning_v1 import (
    ensure_account_learning_schema_v1,
    set_account_learning_watch_v1,load_account_learning_watches_v1,
    load_account_learning_findings_v1,propose_account_learning_v1,
    run_account_learning_cycle_v1,
)

BASE=datetime(2026,10,20,12,0,tzinfo=timezone.utc)


def sample(n,amount,*,account="account-a",strategy="macd-flip",
           armed=True,identity="inst-a",reliability="Ok"):
    context=[{"live_armed":armed,"strategy":strategy,
              "instance_id":identity,"timeframe":"2m","market":"Tech100"}]
    return {"account_id":account,"account_name":"Test Account",
            "currency":"NOK",
            "observed_at":(BASE+timedelta(minutes=5*n)).isoformat(),
            "total_value":amount,"calculation_reliability":reliability,
            "context_json":json.dumps(context)}


def execution(n,action,*,account="account-a",instance="inst-a",side="Buy"):
    return {"request_key":f"req-{n}","account_id":account,
            "instance_id":instance,"market_name":"Tech100",
            "action":action,"side":side,"direction":"LONG",
            "amount":.01,"inventory_before":0.,"inventory_after":.01,
            "executed_at":(BASE+timedelta(minutes=n)).isoformat()}


def history():
    return tuple(sample(n,value) for n,value in enumerate(
        [1000,995,993,987,980,970]))


def activity():
    return (execution(6,"OPEN"),execution(11,"CLOSE",side="Sell"),
            execution(16,"OPEN"),execution(21,"CLOSE",side="Sell"))


def test_negative_nav_with_matching_turnover_is_only_sim_hypothesis():
    findings=propose_account_learning_v1(
        account_id="account-a",samples=history(),executions=activity(),
        now=BASE+timedelta(minutes=27))
    assert len(findings)==1
    a=findings[0]
    assert a.kind=="TEST_PRICE_CONFIRMED_ANTI_CHURN"
    assert a.status=="RESEARCH_ONLY"
    assert "SIM A/B" in a.test_plan
    assert a.confidence_scope=="OBSERVATIONAL_NAV_NOT_STRATEGY_PNL"
    evidence=json.loads(a.evidence_json)
    assert evidence["confirmed_v3_orders"]==4
    assert evidence["verified_strategy_net_pnl"] is None
    assert evidence["cashflows_reconciled"] is False


def test_unknown_order_ledger_does_not_fabricate_zero_turnover():
    f=propose_account_learning_v1(
        account_id="account-a",samples=history(),executions=None,
        now=BASE+timedelta(minutes=27))
    assert len(f)==1
    assert f[0].kind=="RECONCILE_NAV_BEFORE_TUNING"
    assert json.loads(f[0].evidence_json)["confirmed_v3_orders"] is None


def test_wrong_account_rejected_even_when_strategy_same():
    with pytest.raises(ValueError,match="cross-account"):
        propose_account_learning_v1(
            account_id="account-a",samples=history(),
            executions=activity()+(execution(19,"OPEN",account="account-b"),),
            now=BASE+timedelta(minutes=27))
    with pytest.raises(ValueError,match="cross-account"):
        propose_account_learning_v1(
            account_id="account-a",samples=history()+(sample(9,400,account="account-b"),),
            executions=activity(),now=BASE+timedelta(minutes=27))


def test_timeframe_change_and_ambiguous_owner_not_misattributed():
    changing=tuple(sample(n,1000-10*n,strategy=(
        "macd-flip" if n<3 else "macd-histogram")) for n in range(6))
    assert propose_account_learning_v1(
        account_id="account-a",samples=changing,
        executions=activity(),now=BASE+timedelta(minutes=27))==()
    unarmed=tuple(sample(n,1000-10*n,armed=False) for n in range(6))
    assert propose_account_learning_v1(
        account_id="account-a",samples=unarmed,
        executions=activity(),now=BASE+timedelta(minutes=27))==()


def test_stale_or_nonverified_nav_yields_no_hypotheses():
    assert propose_account_learning_v1(
        account_id="account-a",samples=history(),executions=activity(),
        now=BASE+timedelta(days=2))==()
    unreliable=tuple(sample(n,1000-10*n,reliability="Unverified")
                     for n in range(6))
    assert propose_account_learning_v1(
        account_id="account-a",samples=unreliable,executions=activity(),
        now=BASE+timedelta(minutes=27))==()
    empty=tuple(sample(n,0) for n in range(6))
    assert propose_account_learning_v1(
        account_id="account-a",samples=empty,executions=activity(),
        now=BASE+timedelta(minutes=27))==()


def test_watch_persistence_idempotency_and_no_execution_mutation(tmp_path):
    db=str(tmp_path/"learning.db")
    for i,row in enumerate(history()):
        save_account_truth_v1(SaxoAccountTruthV1(
            account_id=row["account_id"],account_name="Test Account",
            currency="NOK",observed_at=BASE+timedelta(minutes=5*i),
            total_value=row["total_value"],cash_balance=980,
            unrealized_margin_pnl=0,financing_accruals=None,
            transactions_not_booked=None,cost_to_close=None,
            margin_used=None,margin_utilization_pct=None,
            calculation_reliability="Ok",
            context_json=row["context_json"]),db_path=db)
    with pytest.raises(ValueError):
        set_account_learning_watch_v1(account_id="account-b",enabled=True,db_path=db)
    set_account_learning_watch_v1(account_id="account-a",enabled=True,db_path=db)
    assert bool(load_account_learning_watches_v1(db_path=db)[0]["enabled"])
    with connect(db) as conn:
        conn.execute("""CREATE TABLE autotrader_v3_execution_events (
            request_key TEXT PRIMARY KEY,account_id TEXT,instance_id TEXT,
            market_name TEXT,action TEXT,side TEXT,direction TEXT,amount REAL,
            inventory_before REAL,inventory_after REAL,executed_at TEXT)""")
        for row in activity():
            conn.execute("""INSERT INTO autotrader_v3_execution_events
                (request_key,account_id,instance_id,market_name,action,
                 side,direction,amount,inventory_before,inventory_after,executed_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",tuple(row.values()))
    one=run_account_learning_cycle_v1(db_path=db,
                                      now=BASE+timedelta(minutes=27))
    two=run_account_learning_cycle_v1(db_path=db,
                                      now=BASE+timedelta(minutes=27))
    assert one["watched_accounts"]==1 and one["new_findings"]==1 and one["errors"]==0
    assert two["new_findings"]==0
    found=load_account_learning_findings_v1(account_id="account-a",db_path=db)
    assert len(found)==1 and found[0]["kind"]=="TEST_PRICE_CONFIRMED_ANTI_CHURN"
    assert load_account_learning_findings_v1(account_id="account-b",db_path=db)==()
    set_account_learning_watch_v1(account_id="account-a",enabled=False,db_path=db)
    assert run_account_learning_cycle_v1(db_path=db)["watched_accounts"]==0
    with connect(db) as conn:
        assert conn.execute("SELECT count(*) AS n FROM autotrader_v3_execution_events").fetchone()["n"]==4


def test_wired_to_telemetry_only_and_separate_navigation():
    worker=Path("telegram_multi_worker.py").read_text()
    nav=Path("navigation_config.py").read_text()
    src=Path("autotrader_account_learning_v1.py").read_text()
    assert "_account_truth_loop_v1" in worker
    assert "learning=run_account_learning_cycle_v1" in worker
    assert "Konto_Laering" in nav
    for absent in ("place_order(","set_live_enabled_v3(", "confirm_live=True",
                   "save_autotrader_config_v3(", "broker.client._post("):
        assert absent not in src
