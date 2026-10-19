"""Saxo balances are read-only account truth; not fabricated profit or attribution."""
from __future__ import annotations

from datetime import datetime,timedelta,timezone
import json
from pathlib import Path

import pytest

import autotrader_saxo_account_truth_v1 as m


NOW=datetime(2026,10,19,1,0,tzinfo=timezone.utc)


def acct(account="one",currency="NOK"):
    return {"AccountId":account,"AccountKey":account+"-key",
            "Currency":currency,"DisplayName":"Tech100-A" if account=="one" else "lager"}


def balance(currency="NOK",total=1010.):
    return {"Currency":currency,"TotalValue":total,"CashBalance":980.,
            "UnrealizedMarginProfitLoss":30.,"FinancingAccruals":-1.5,
            "TransactionsNotBooked":0.,"CostToClosePositions":-3.,
            "MarginUsedByCurrentPositions":-350.,"MarginUtilizationPct":35.,
            "CalculationReliability":"Ok"}


class Client:
    def __init__(self):
        self.timeout=20
        self.calls=[]
    def _get(self,path,params=None):
        assert path=="port/v1/balances"
        self.calls.append((path,params))
        assert list(params)==["AccountKey"]
        if params["AccountKey"]=="one-key":return balance()
        if params["AccountKey"]=="two-key":return balance("USD",150.)
        raise AssertionError("unknown account key")
    def _post(self,*args,**kw):
        raise AssertionError("READ ONLY: broker POST forbidden")


class Broker:
    def __init__(self):
        self.client=Client()
        self._accounts=(acct("one"),acct("two","USD"))
        self.calls=[]
    def accounts(self):
        self.calls.append("accounts")
        return self._accounts
    def place_order(self,*args,**kw):
        raise AssertionError("collector may NEVER trade")
    def precheck(self,*args,**kw):
        raise AssertionError("precheck POST forbidden")


def test_strict_saxo_account_currency_source_and_missing_total():
    sample=m.parse_saxo_balance_v1(
        account=acct(),payload=balance(),observed_at=NOW)
    assert sample.total_value==1010
    assert sample.cash_balance==980
    assert sample.verified
    assert sample.financing_accruals==-1.5
    assert sample.currency=="NOK"
    assert sample.context_json=="[]"
    for bad in [
        dict(balance(),Currency="USD"),
        dict(balance(),TotalValue=None),
        dict(balance(),TotalValue=float("nan")),
        dict(balance(),CashBalance=True),
        dict(balance(),FinancingAccruals=float("inf")),
        dict(balance(),AccountId="foreign"),
    ]:
        with pytest.raises(ValueError):
            m.parse_saxo_balance_v1(account=acct(),payload=bad,observed_at=NOW)


def test_missing_optional_fields_remain_unknown_not_zero():
    result=m.parse_saxo_balance_v1(
        account=acct(),payload={"Currency":"NOK","TotalValue":100.,
                                "CalculationReliability":"Ok"},observed_at=NOW)
    assert result.cash_balance is None
    assert result.unrealized_margin_pnl is None
    assert result.margin_used is None


def test_broker_unreliable_sample_stored_but_never_used_for_return():
    result=m.parse_saxo_balance_v1(
        account=acct(),payload=dict(balance(),CalculationReliability="StalePrice"),
        observed_at=NOW)
    assert not result.verified
    assert m.account_value_summary_v1([{
        "account_id":"one","currency":"NOK",
        "calculation_reliability":"StalePrice",
        "total_value":1010.,
    }])["value_change"] is None


def test_collect_both_saxo_accounts_in_own_currency_into_durable_sqlite(monkeypatch,tmp_path):
    db=str(tmp_path/"ledger.sqlite")
    monkeypatch.setattr(m,"_account_strategy_context_v1",
        lambda **kw:{"one":({"instance_id":"techA","strategy":"macd-stoch-v2",
                             "market":"US Tech 100 NAS","market_close":20100.,
                             "market_bar_at":NOW.isoformat(),
                             "timeframe":"1m"},)})
    broker=Broker()
    report=m.collect_saxo_account_truth_once_v1(
        broker=broker,db_path=db,now=NOW)
    assert report=={"status":"OK","seen":2,"saved":2,"failed":0}
    assert broker.calls==["accounts"]
    assert [p[1] for p in broker.client.calls]==[
        {"AccountKey":"one-key"},{"AccountKey":"two-key"}]
    assert broker.client.timeout==5
    # Same 5 minute slot cannot overwrite a prior observation.
    duplicate=m.collect_saxo_account_truth_once_v1(
        broker=broker,db_path=db,now=NOW+timedelta(seconds=80))
    assert duplicate["saved"]==0
    one=m.load_account_truth_v1(account_id="one",days=180,db_path=db)
    # The historical 2026-10 date may be outside the test runner's 180-day clock.
    from database import connect
    with connect(db,force_sqlite=True) as conn:
        rows=conn.execute(
            "SELECT * FROM pg_saxo_account_truth_v1 ORDER BY account_id"
        ).fetchall()
    assert len(rows)==2
    assert rows[0]["currency"]=="NOK"
    assert rows[1]["currency"]=="USD"
    assert rows[0]["source"]==m.SOURCE
    context=json.loads(rows[0]["context_json"])
    assert context[0]["strategy"]=="macd-stoch-v2"
    assert context[0]["market_close"]==20100.


def test_account_change_is_not_profit_before_flow_reconciliation():
    a={"account_id":"one","currency":"NOK","total_value":1000.,
       "observed_at":"2026-10-19T00:00:00+00:00","calculation_reliability":"Ok"}
    b=dict(a,total_value=1250.,observed_at="2026-10-19T01:00:00+00:00")
    result=m.account_value_summary_v1([a,b])
    assert result["value_change"]==250
    assert result["trading_profit_nok"] is None
    assert result["flow_adjusted_return_pct"] is None
    assert result["status"]=="CASH_FLOWS_AND_BOOKED_COSTS_NOT_RECONCILED"
    assert m.account_value_summary_v1([a,dict(b,account_id="foreign")])["value_change"] is None
    assert m.account_value_summary_v1([a,dict(b,currency="USD")])["value_change"] is None


def test_collector_isolation_per_failed_account_and_does_not_log_secrets(monkeypatch,tmp_path):
    db=str(tmp_path/"isolation.sqlite")
    class FailingBroker(Broker):
        def __init__(self):
            super().__init__()
            self.client._get=lambda path,params: (_ for _ in ()).throw(
                RuntimeError("secret token ACCOUNTID 12345"))
    monkeypatch.setattr(m,"_account_strategy_context_v1",lambda **kw:{})
    broker=FailingBroker()
    report=m.collect_saxo_account_truth_once_v1(broker=broker,db_path=db)
    assert report=={"status":"PARTIAL","seen":2,"saved":0,"failed":2}
    assert "secret" not in repr(report)


def test_worker_thread_collects_in_independent_daemon_and_never_mutates_authority():
    worker=Path("telegram_multi_worker.py").read_text()
    assert 'target=_account_truth_loop_v1' in worker
    assert 'name="pricegauger-saxo-account-truth"' in worker
    assert "stop_event.wait(COLLECTION_SECONDS)" in worker
    assert "collect_saxo_account_truth_once_v1" in worker
    assert "set_live_authority_v3" not in m.__file__


def test_account_statistics_page_is_navigable_and_reports_unreconciled_profit():
    nav=Path("navigation_config.py").read_text()
    page=Path("pages/0_Kontostatistikk.py").read_text()
    assert "0_Kontostatistikk.py" in nav
    assert "autotrader_v3_execution_events" in page
    assert "market_close" in page
    assert "CASH_FLOWS_AND_BOOKED_COSTS_NOT_RECONCILED" in Path(
        "autotrader_saxo_account_truth_v1.py").read_text()
    assert "Kontoverdi over tid" in page
    assert "IKKE AVSTEMT" in page
