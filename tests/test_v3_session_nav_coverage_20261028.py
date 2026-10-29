"""Regression on 28 Oct: lab showed partial 6-account subtotal as full day.

The Saxo app screenshots showed several losing Tech100 accounts, but the lab
displayed a 1620.51->1603.43 NAV subset and lacked timestamp provenance.
These checks enforce no synthetic day total when account/snapshot clocks differ.
"""
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace

import pytest

from autotrader_v3_session_loss_lab_v1 import (
    funded_account_cohort_v1,account_session_result,
    summarize_fleet_sessions,oslo_session_start,
)

START=oslo_session_start(datetime(2026,10,28).date())
END=START+timedelta(hours=9)


def snap(account,tick,total,ccy="NOK"):
    return {
        "account_id":account,"account_name":"Tech100-"+account,
        "currency":ccy,"total_value":total,
        "calculation_reliability":"Ok",
        "observed_at":(START+timedelta(minutes=tick)).isoformat(),
    }


def result(a,rows):
    return account_session_result(
        account_id=a,samples=rows,start=START,end=END)


def test_funded_cohort_keeps_missing_03_baselines_and_excludes_zero_silver():
    source=(
        snap("A",1,950.),snap("A",539,945.),
        snap("B",420,120.),snap("B",538,110.),
        snap("C",1,150.),snap("C",540,145.),
        snap("D",1,0.),snap("D",540,0.),
    )
    funded,zero=funded_account_cohort_v1(samples=source,end=END)
    assert set(funded)=={"A","B","C"}
    assert zero==("Tech100-D",)
    actual=(result("A",source[:2]),result("B",source[2:4]),
            result("C",source[4:6]))
    subtotal=summarize_fleet_sessions(actual)[0]
    assert subtotal["accounts"]==2
    assert subtotal["expected_funded_accounts"]==3
    assert subtotal["excluded_accounts"]==1
    assert subtotal["status"]=="MISSING_ACCOUNT_BASELINE_OR_END"
    assert subtotal["unadjusted_nav_pct"] is None
    assert subtotal["start_total"] is None
    assert subtotal["end_total"] is None
    assert subtotal["subtotal_change_only"]==-10.


def test_out_of_sync_latest_snapshots_cannot_be_presented_as_fleet_daily():
    early=result("A",(snap("A",1,950.),snap("A",530,945.)))
    late=result("B",(snap("B",2,120.),snap("B",539,110.)))
    total=summarize_fleet_sessions((early,late))[0]
    assert total["accounts"]==2
    assert total["status"]=="ACCOUNT_TIMES_NOT_ALIGNED"
    assert total["last_spread_minutes"]==9
    assert total["unadjusted_nav_pct"] is None


def test_full_funded_cohort_synchronized_can_show_observed_not_official_pct():
    a=result("A",(snap("A",1,950.),snap("A",538,945.)))
    b=result("B",(snap("B",2,120.),snap("B",540,110.)))
    total=summarize_fleet_sessions((a,b))[0]
    assert total["status"]=="OBSERVED_COHORT_APPROX"
    assert total["accounts"]==total["expected_funded_accounts"]==2
    assert total["unadjusted_nav_delta"]==-15.
    assert total["start_total"]==1070.
    assert total["end_total"]==1055.
    assert total["unadjusted_nav_pct"]==pytest.approx(100*-15/1070)
    assert "not Saxo daily performance" in total["warning"]


def test_cohort_rejects_values_recorded_after_analysis_end():
    funded,_=funded_account_cohort_v1(
        samples=(snap("A",540,10.),snap("B",541,100.),snap("C",539,0.)),
        end=END)
    assert set(funded)=={"A"}


def test_ui_exposes_both_clocks_and_stale_cached_report():
    from pathlib import Path
    s=Path("pages/0_AutoTrader_Loss_Lab.py").read_text()
    assert '"report_generated_at"' in s
    assert "minutes_old>=5" in s
    assert "funded_account_cohort_v1(" in s
    assert '"Avvik fra 03 (min)"' in s
    assert 'if row["Avvik fra 03 (min)"] is not None' in s
    assert '"Sluttid norsk"' in s
    assert "ingen gyldig samlet dagsprosent" in s.lower()
    assert "st.container(border=True)" in s
    assert 'saxo' in s.lower()
    assert "place_order(" not in s



def test_02_59_snapshot_closer_than_03_04_is_used_with_signed_offset():
    # Real telemetry cadence verified: samples at 02:59:32 and 03:04:42 Oslo.
    before=snap("A",-0.4667,100.)
    after=snap("A",4.7,96.)
    latest=snap("A",539,94.)
    out=account_session_result(
        account_id="A",samples=(before,after,latest),
        start=START,end=END)
    assert out.baseline_value==100.
    assert out.start_observed_at<START
    assert out.baseline_delay_minutes==pytest.approx(-.4667,abs=.002)
    assert out.nav_change_pct==pytest.approx(-6.)
    assert out.status=="OBSERVED_NAV_UNADJUSTED"
    assert out.samples==3


def test_nearest_baseline_can_be_post_reset_and_earlier_sample_excluded():
    # A closer 03:00:12 sample should win over a 02:58:30 one.
    earlier=snap("A",-1.5,110.)
    first=snap("A",.2,100.)
    last=snap("A",539,95.)
    out=result("A",(earlier,first,last))
    assert out.baseline_value==100.
    assert out.samples==2
    assert out.nav_change_pct==-5.
    assert out.worst_observed_drawdown_pct==pytest.approx(5.)


def test_funded_accounts_are_not_hidden_when_only_saxo_quality_unverified():
    unverified=snap("A",500,111.)
    unverified["calculation_reliability"]="Unverified"
    funded,zero=funded_account_cohort_v1(samples=(unverified,),end=END)
    assert funded=={"A":"Tech100-A"}
    assert not zero
    result=account_session_result(account_id="A",samples=(unverified,),
        start=START,end=END)
    assert result.status=="NO_VERIFIED_NAV"
    fleet=summarize_fleet_sessions((result,))[0]
    assert fleet["expected_funded_accounts"]==1
    assert fleet["status"]=="MISSING_ACCOUNT_BASELINE_OR_END"
    assert fleet["unadjusted_nav_pct"] is None
