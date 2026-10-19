"""Accounts with no broker EOD history should not trigger hourly error retries."""
from datetime import datetime, timezone
from pathlib import Path

from database import connect
from autotrader_saxo_official_performance_v1 import (
    collect_official_performance_once_v1,load_official_performance_v1,
)

NOW=datetime(2026,10,19,15,0,tzinfo=timezone.utc)


class Broker:
    def __init__(self):
        self.timeout=20
        self.client=self
        self.calls=[]
    def accounts(self):
        return tuple(dict(AccountId=f"account-{i}",AccountKey=f"key-{i}",
                          ClientKey="client",Currency="NOK")
                     for i in range(12))
    def _get(self,path,params):
        self.calls.append((path,params["AccountKey"]))
        if int(params["AccountKey"].split("-")[1])>=4:
            return {}  # Exact Saxo GET returned without any performance history.
        if path.endswith("timeseries"):
            return {"Balance":{"AccountValue":[
                {"Date":"2026-10-18","Value":1000.}]}}
        return {"AccumulatedProfitLoss":15.,
                "From":"2026-07-21","Thru":"2026-10-19"}
    def _post(self,*args,**kwargs):
        raise AssertionError("GET-only")
    def place_order(self,*args,**kwargs):
        raise AssertionError("No broker orders")


def test_four_funded_eight_without_history_are_normal(tmp_path):
    db=str(tmp_path/"eod.db")
    broker=Broker()
    result=collect_official_performance_once_v1(
        broker=broker,db_path=db,now=NOW)
    assert result==dict(status="OK",seen=12,saved=4,failed=0,
                        skipped_no_history=8)
    assert len(broker.calls)==24
    assert broker.timeout==5.
    with connect(db,force_sqlite=True) as connection:
        rows=connection.execute(
            "SELECT status,profit,last_trade_day FROM "
            "pg_saxo_account_perf_summary_v1 ORDER BY account_id").fetchall()
    assert len(rows)==12
    assert [r["status"] for r in rows].count("BROKER_HISTORY_EMPTY")==8
    assert [r["status"] for r in rows].count("SAXO_REPORTED_ACCOUNT_PNL")==4
    assert all(r["profit"] is None for r in rows
               if r["status"]=="BROKER_HISTORY_EMPTY")
    daily,summary=load_official_performance_v1(
        account_id="account-7",db_path=db)
    assert not daily
    assert summary["status"]=="BROKER_HISTORY_EMPTY"
    assert summary["profit"] is None
    # Repeated collection is idempotent rather than inventing zero returns.
    again=collect_official_performance_once_v1(
        broker=broker,db_path=db,now=NOW)
    assert again==result
    with connect(db,force_sqlite=True) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM pg_saxo_account_perf_summary_v1"
        ).fetchone()[0]==12


def test_worker_uses_normal_daily_cadence_when_all_requests_succeed():
    src=Path("telegram_multi_worker.py").read_text()
    assert '24*3600 if history["status"]=="OK" else 3600' in src
    assert 'history.get("skipped_no_history",0)' in src
    ui=Path("pages/0_Kontostatistikk.py").read_text()
    assert 'official["status"]=="BROKER_HISTORY_EMPTY"' in ui
