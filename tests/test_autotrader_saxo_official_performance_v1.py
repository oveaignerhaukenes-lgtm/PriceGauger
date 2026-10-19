"""Broker-calculated EOD P/L and time-weighted performance: no fabricated profits."""
from __future__ import annotations

from datetime import date,datetime,timezone
from pathlib import Path

import pytest
import autotrader_saxo_official_performance_v1 as m

START=date(2026,10,1)
END=date(2026,10,19)
NOW=datetime(2026,10,19,2,0,tzinfo=timezone.utc)


def times():
    return {
        "Balance":{
            "AccountValue":[{"Date":"2026-10-17","Value":1000.},
                            {"Date":"2026-10-18","Value":950.}],
            "CashTransfer":[{"Date":"2026-10-18","Value":-100.}],
        },
        "TimeWeighted":{"Accumulated":[{"Date":"2026-10-17","Value":0.0},
                                       {"Date":"2026-10-18","Value":0.05}]},
    }


def summary():
    return {"From":"2026-10-01","Thru":"2026-10-18",
            "LastTradeDay":"2026-10-18","AccumulatedProfitLoss":50.}


def test_official_time_series_retains_missing_values_and_transfer():
    rows=m.parse_official_performance_v1(times(),from_date=START,to_date=END)
    assert [x["value_date"] for x in rows]==["2026-10-17","2026-10-18"]
    assert rows[0]["cash_transfer"] is None  # NOT invented as zero
    assert rows[1]["account_value"]==950
    assert rows[1]["cash_transfer"]==-100
    assert rows[1]["time_weighted_fraction"]==.05
    assert rows[0]["time_weighted_fraction"]==0.


def test_reported_pnl_is_source_not_difference_in_account_value():
    result=m.parse_saxo_profit_summary_v1(summary(),from_date=START,to_date=END)
    assert result=={"status":"SAXO_REPORTED_ACCOUNT_PNL",
                    "profit":50.,"last_trade_day":"2026-10-18"}
    assert result["profit"] != 950-1000


@pytest.mark.parametrize("bad",[
    {"Balance":{"AccountValue":[{"Date":"2026-10-18","Value":float("nan")}]}},
    {"Balance":{"AccountValue":[{"Date":"2026-10-18","Value":True}]}},
    {"Balance":{"AccountValue":[{"Date":"2026-10-18","Value":1},
                                {"Date":"2026-10-18","Value":2}]}},
    {"Balance":{"AccountValue":[{"Date":"2028-10-18","Value":1}]}},
    {"TimeWeighted":{"Accumulated":"bad"}},
])
def test_invalid_numeric_date_duplicate_or_structure_is_rejected(bad):
    with pytest.raises((ValueError,TypeError)):
        m.parse_official_performance_v1(bad,from_date=START,to_date=END)


def test_missing_broker_pnl_never_assumed_zero():
    result=m.parse_saxo_profit_summary_v1(
        {"AccumulatedProfitLoss":None},from_date=START,to_date=END)
    assert result["profit"] is None
    assert result["status"]=="BROKER_PNL_MISSING"


def test_persist_broker_daily_and_summary_without_using_cashflows_as_profit(tmp_path):
    db=str(tmp_path/"performance.db")
    rows=m.parse_official_performance_v1(times(),from_date=START,to_date=END)
    summary_data=m.parse_saxo_profit_summary_v1(summary(),from_date=START,to_date=END)
    m.save_official_performance_v1(
        account_id="one",currency="NOK",daily=rows,
        summary=summary_data,from_date=START,to_date=END,
        observed_at=NOW,db_path=db)
    from database import connect
    with connect(db,force_sqlite=True) as con:
        daily=con.execute("SELECT * FROM pg_saxo_account_perf_daily_v1 "
                          "WHERE account_id='one' ORDER BY value_date").fetchall()
        result=con.execute("SELECT * FROM pg_saxo_account_perf_summary_v1 "
                           "WHERE account_id='one'").fetchone()
    assert len(daily)==2
    assert daily[1]["time_weighted_fraction"]==.05
    assert daily[1]["cash_transfer"]==-100
    assert result["profit"]==50.
    assert result["currency"]=="NOK"
    # Reprocessing official Saxo day refreshes instead of duplicating.
    m.save_official_performance_v1(
        account_id="one",currency="NOK",daily=rows,
        summary=summary_data,from_date=START,to_date=END,
        observed_at=NOW,db_path=db)
    with connect(db,force_sqlite=True) as con:
        assert con.execute(
            "SELECT count(*) FROM pg_saxo_account_perf_daily_v1").fetchone()[0]==2


class Broker:
    def __init__(self):
        self.calls=[]
        self.client=self
        self.timeout=20
    def accounts(self):
        return ({"AccountId":"one","AccountKey":"key-one","ClientKey":"c1",
                 "Currency":"NOK"},)
    def _get(self,path,params=None):
        self.calls.append((path,params))
        assert params["AccountKey"]=="key-one"
        assert params["ClientKey"]=="c1"
        assert params["ToDate"]=="2026-10-19"
        if path=="hist/v4/performance/timeseries":
            assert "TimeWeighted_Accumulated" in params["FieldGroups"]
            return times()
        if path=="hist/v4/performance/summary":
            assert "FieldGroups" not in params
            return summary()
        raise AssertionError(path)
    def _post(self,*args,**kwargs):raise AssertionError("POST forbidden")
    def place_order(self,*args,**kwargs):raise AssertionError("Orders forbidden")


def test_readonly_actual_broker_historical_collection(tmp_path):
    db=str(tmp_path/"history.db")
    b=Broker()
    result=m.collect_official_performance_once_v1(
        broker=b,db_path=db,now=NOW,days=18)
    assert result=={"status":"OK","seen":1,"saved":1,"failed":0}
    assert b.timeout==5.
    assert [v[0] for v in b.calls]==[
        "hist/v4/performance/timeseries","hist/v4/performance/summary"]
    assert "password" not in str(result)


def test_worker_reads_hist_independently_and_ui_labels_eod_as_account_wide():
    worker=Path("telegram_multi_worker.py").read_text()
    page=Path("pages/0_Kontostatistikk.py").read_text()
    assert "collect_official_performance_once_v1" in worker
    assert "next_official_check" in worker
    assert "TimeWeighted_Accumulated" in Path(
        "autotrader_saxo_official_performance_v1.py").read_text()
    assert "Saxo offisiell historisk kontoperformance" in page
    assert "ikke bare valgt autotrader" in page
    assert "Forespurt periode" in page
