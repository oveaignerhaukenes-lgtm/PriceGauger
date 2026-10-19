"""Saxo equity and LIVE strategy observations are evidence, never guessed profit."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from autotrader_saxo_strategy_timeline_v1 import observed_live_nav_windows_v1
import autotrader_saxo_official_performance_v1 as perf

T0=datetime(2026,10,19,11,0,tzinfo=timezone.utc)


def sample(minutes, *, strategy="macd-stoch-v2", amount=1000, active=True,
           quality="Ok", contexts=None, account="a", currency="NOK"):
    if contexts is None:
        contexts=[dict(instance_id="t",strategy=strategy,timeframe="1m",
                       market="Tech100",live_armed=active)]
    return dict(account_id=account,currency=currency,observed_at=(T0+
        timedelta(minutes=minutes)).isoformat(),total_value=amount,
        calculation_reliability=quality,context_json=json.dumps(contexts))


def test_windows_do_not_assign_switch_boundary_to_either_strategy():
    rows=[sample(0,amount=1000),sample(5,amount=1020),
          sample(10,strategy="rhythm-trend-1",amount=1300),
          sample(15,strategy="rhythm-trend-1",amount=1270)]
    windows=observed_live_nav_windows_v1(rows)
    assert len(windows)==2
    assert [w.strategy_key for w in windows]==["macd-stoch-v2","rhythm-trend-1"]
    assert [w.value_change for w in windows]==[20,-30]
    assert [round(w.value_change_pct,2) for w in windows]==[2.,-2.31]
    # The +280 jump at the transition cannot be called strategy profit.
    assert sum(w.value_change for w in windows)==-10


def test_windows_break_for_quality_gaps_off_and_ambiguous_ownership():
    rows=[sample(0,amount=1000),sample(5,amount=1030),
          sample(10,amount=1300,quality="StalePrice"),
          sample(15,amount=1400),sample(20,amount=1410),
          sample(40,amount=2000),sample(45,amount=1995),
          sample(50,amount=1800,active=False),
          sample(55,amount=1900,contexts=[
              dict(instance_id="t",strategy="macd",live_armed=True),
              dict(instance_id="other",strategy="stoch",live_armed=True)]),
          sample(60,amount=2100)]
    result=observed_live_nav_windows_v1(rows)
    assert len(result)==4
    assert [w.observations for w in result]==[2,2,2,1]
    assert [w.value_change for w in result]==[30,10,-5,None]
    assert result[-1].value_change_pct is None
    assert result[0].currency=="NOK"


def test_drawdown_observed_not_realized_after_cost_pnl():
    windows=observed_live_nav_windows_v1([
        sample(0,amount=1000),sample(5,amount=1050),sample(10,amount=950)])
    assert len(windows)==1
    assert windows[0].value_change==-50
    assert windows[0].value_change_pct==pytest.approx(-5)
    assert windows[0].max_observed_drawdown_pct==pytest.approx(100/1050*100)


def test_no_cross_account_or_currency_or_time_bridge():
    for other in (sample(5,account="b"),sample(5,currency="USD")):
        with pytest.raises(ValueError,match="cannot mix Saxo account/currency"):
            observed_live_nav_windows_v1([sample(0),other])
    assert observed_live_nav_windows_v1([])==()
    with pytest.raises(ValueError,match="max_gap_seconds"):
        observed_live_nav_windows_v1([sample(0)],max_gap_seconds=0)


def test_saxo_official_partial_failures_report_safe_stage_only(tmp_path):
    class ApiFailure(Exception):
        status_code=404
    class Client:
        timeout=10
        def _get(self,path,params):
            if params["AccountKey"]=="account-2" and path.endswith("summary"):
                raise ApiFailure("secret token never leak")
            if path.endswith("timeseries"):
                return {"Balance":{"AccountValue":[
                    {"Date":"2026-10-18","Value":1000.}]}}
            return {"AccumulatedProfitLoss":15.,
                    "From":"2026-10-01","Thru":"2026-10-19"}
    class Broker:
        client=Client()
        def accounts(self):
            return tuple(dict(AccountId=f"a{i}",AccountKey=f"account-{i}",
                ClientKey="c",Currency="NOK") for i in (1,2))
    report=perf.collect_official_performance_once_v1(
        broker=Broker(),days=18,db_path=str(tmp_path/"official.db"),now=T0)
    assert report=={"status":"PARTIAL","seen":2,"saved":1,"failed":1,
                    "errors":{"SUMMARY_GET_HTTP_404":1}}
    assert "secret" not in repr(report)
    assert "account-2" not in repr(report)
    assert "error_codes=%s" in Path("telegram_multi_worker.py").read_text()


def test_ui_displays_unreconciled_observed_windows_not_synthetic_profit():
    page=Path("pages/0_Kontostatistikk.py").read_text()
    source=Path("autotrader_saxo_account_truth_v1.py").read_text()
    assert "observed_live_nav_windows_v1(samples_for_chart)" in page
    assert "IKKE dokumentert strategi-P/L" in page
    assert "50 000 nyeste målingene" in page
    assert 'if account_id else "ORDER BY observed_at DESC, account_id DESC LIMIT 50000"' in source
