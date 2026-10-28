"""03:00 Oslo loss forensics: data provenance, timezone, causal replay boundary."""
from datetime import datetime,date,timedelta,timezone
from math import sin
from types import SimpleNamespace

import pytest

from autotrader_v3_session_loss_lab_v1 import (
    OSLO,oslo_session_start,current_oslo_session,
    account_session_result,summarize_fleet_sessions,
    filter_reconciled_account_fills,classify_completed_regime,
    split_completed_regimes,market_session_coverage,replay_session_delta,proposal_from_evidence,
    fill_price_followthrough,
)

DAY=date(2026,10,28)
START=oslo_session_start(DAY)
END=START+timedelta(hours=7)


def sample(at,value,account="A",currency="NOK",good=True):
    return dict(account_id=account,account_name="Tech100-"+account,
                currency=currency,observed_at=at.isoformat(),
                total_value=value,calculation_reliability="Ok" if good else "Unverified",
                context_json="[]")


def candle(i,price,op=None):
    t=START+timedelta(minutes=i)
    opening=price if op is None else op
    return SimpleNamespace(
        bar_time=t.isoformat(),open=opening,close=price,
        high=max(price,opening)+.5,low=min(price,opening)-.5,
        market_name="US Tech 100 NAS",volume=1.,quality_flags=1,
    )


def test_03_oslo_calendar_boundary_including_dst():
    assert START.isoformat()=="2026-10-28T02:00:00+00:00"
    assert oslo_session_start(date(2026,7,28)).isoformat()=="2026-07-28T01:00:00+00:00"
    assert current_oslo_session(
        now=datetime(2026,10,28,1,30,tzinfo=timezone.utc)
    )==oslo_session_start(date(2026,10,27))
    assert current_oslo_session(
        now=datetime(2026,10,28,2,0,tzinfo=timezone.utc)
    )==START


def test_first_valid_quote_after_reset_no_before_or_future_interpolation():
    rows=[
        sample(START-timedelta(minutes=4),110.),
        sample(START+timedelta(minutes=1),100.),
        sample(START+timedelta(minutes=6),90.,good=False),
        sample(START+timedelta(minutes=11),95.),
    ]
    result=account_session_result(
        account_id="A",samples=rows,start=START,end=START+timedelta(minutes=12))
    assert result.baseline_value==100.
    assert result.latest_value==95.
    assert result.nav_change==-5.
    assert result.nav_change_pct==-5.
    assert result.samples==2
    assert result.status=="OBSERVED_NAV_UNADJUSTED"
    assert result.baseline_delay_minutes==1.


def test_no_baseline_fabricated_after_long_data_gap():
    rows=[sample(START+timedelta(minutes=22),100.),
          sample(START+timedelta(minutes=35),94.)]
    result=account_session_result(
        account_id="A",samples=rows,start=START,end=START+timedelta(minutes=40))
    assert result.status=="BASELINE_TOO_LATE"
    assert result.nav_change_pct is None
    incomplete=summarize_fleet_sessions((result,))
    assert len(incomplete)==1
    assert incomplete[0]["status"]=="MISSING_ACCOUNT_BASELINE_OR_END"
    assert incomplete[0]["accounts"]==0
    assert incomplete[0]["expected_funded_accounts"]==1
    assert incomplete[0]["unadjusted_nav_pct"] is None


def test_cross_currency_and_cross_account_never_aggregate():
    start=sample(START,100.,account="A")
    after=sample(START+timedelta(minutes=5),92.,account="A")
    result=account_session_result(
        account_id="A",samples=(start,after),
        start=START,end=START+timedelta(minutes=6))
    other=account_session_result(
        account_id="B",samples=[
            sample(START,50.,account="B",currency="USD"),
            sample(START+timedelta(minutes=5),60.,account="B",currency="USD"),
        ],start=START,end=START+timedelta(minutes=6))
    totals=summarize_fleet_sessions((result,other))
    assert len(totals)==2
    assert {x["currency"]:x["unadjusted_nav_pct"] for x in totals}=={
        "NOK":-8.,"USD":20.}
    with pytest.raises(ValueError,match="cross-account"):
        account_session_result(account_id="A",samples=(start,
            sample(START,95.,account="B")),start=START,end=END)


def test_fills_are_exact_account_and_time_and_unknown_is_not_zero():
    assert filter_reconciled_account_fills(
        executions=None,account_id="A",start=START,end=END) is None
    fills=filter_reconciled_account_fills(
        executions=[
            dict(account_id="A",executed_at=(START-timedelta(seconds=1)).isoformat()),
            dict(account_id="A",executed_at=(START+timedelta(minutes=7)).isoformat()),
        ],account_id="A",start=START,end=END)
    assert len(fills)==1
    with pytest.raises(ValueError,match="cross-account"):
        filter_reconciled_account_fills(executions=[
            dict(account_id="B",executed_at=START.isoformat())],
            account_id="A",start=START,end=END)


def test_completed_oscillation_regime_cannot_become_live_signal():
    prices=[100+2*sin(i*1.6) for i in range(30)]
    wave=[candle(i,p) for i,p in enumerate(prices)]
    label=classify_completed_regime(wave)
    assert label is not None
    assert label.regime=="SIDEVEIS_RYTME_WHIPSAW_KANDIDAT"
    assert label.efficiency_ratio<.24
    trend=[candle(i,100+i*.9) for i in range(30)]
    stronger=classify_completed_regime(trend)
    assert stronger.regime=="RETNINGSTREND_KANDIDAT"
    assert stronger.efficiency_ratio>0.9
    damaged=wave[:15]+wave[16:]
    assert classify_completed_regime(damaged) is None
    assert split_completed_regimes(wave,minutes=30,start=START,
                                   end=START+timedelta(minutes=30))
    assert not split_completed_regimes(damaged,minutes=30,start=START,
                                      end=START+timedelta(minutes=30))


def test_paper_session_comparison_uses_actual_observed_baseline():
    r=SimpleNamespace(
        strategy="v2",cost_source="MANUAL_SCENARIO",
        events=(
            SimpleNamespace(at=START+timedelta(minutes=3)),
            SimpleNamespace(at=START-timedelta(minutes=5)),
        ),
        points=(
            SimpleNamespace(at=START-timedelta(minutes=1),nav_nok=1000,lots=.01),
            SimpleNamespace(at=START+timedelta(minutes=1),nav_nok=999,lots=.01),
            SimpleNamespace(at=START+timedelta(minutes=3),nav_nok=998,lots=.02),
        ))
    result=replay_session_delta(r,start=START,end=END)
    assert result["paper_change_pct"]==pytest.approx(-100/999)
    assert result["session_decision_events"]==1
    assert result["start_position_lots"]==.01
    assert "PAPER" in result["warning"]


def test_proposals_are_research_only_and_never_issued_as_orders():
    regs=(classify_completed_regime([
        candle(i,100+2*sin(i*1.6)) for i in range(30)]),)
    accounts=(SimpleNamespace(nav_change_pct=-2.,status="OBSERVED_NAV_UNADJUSTED"),
              SimpleNamespace(nav_change_pct=-4.,status="OBSERVED_NAV_UNADJUSTED"))
    titles=[x[0] for x in proposal_from_evidence(
        regimes=regs,account_results=accounts,executions_available=True)]
    assert "Retningsfilter + anti-churn" in titles
    assert "Korrelert kontorisiko" in titles


def test_ui_requires_03_oslo_and_disables_trading_control():
    from pathlib import Path
    s=Path("pages/0_AutoTrader_Loss_Lab.py").read_text()
    nav=Path("navigation_config.py").read_text()
    assert 'oslo_session_start(day)' in s
    assert 'load_account_truth_v1(days=14)' in s
    assert 'replay_v3_strategy_v2(' in s
    assert 'live_orders_changed":False' in s
    assert 'AutoTrader · Taps- og regimelab' in s
    assert 'AutoTrader_Loss_Lab' in nav
    assert "place_order(" not in s
    assert "save_autotrader_config_v3(" not in s
    assert "set_live_authority_v3(" not in s



def test_exact_reconciled_fill_future_retuses_real_next_open_not_fill_price():
    rows=[candle(i,100+i,100+i-.2) for i in range(15)]
    event=dict(account_id="A",executed_at=(
        START+timedelta(minutes=2,seconds=12)).isoformat(),
        inventory_after=.01,instance_id="i1",action="OPEN")
    result=fill_price_followthrough(
        fills=(event,),bars=rows,account_id="A")
    assert len(result)==1
    assert result[0]["first_post_confirmation_price_at"]==START+timedelta(minutes=3)
    assert result[0]["signed_future_1m_bps"]>0
    short=fill_price_followthrough(
        fills=(dict(event,inventory_after=-.01),),bars=rows,account_id="A")
    assert short[0]["signed_future_1m_bps"]<0
    assert fill_price_followthrough(fills=None,bars=rows,account_id="A") is None
    with pytest.raises(ValueError,match="cross-account"):
        fill_price_followthrough(
            fills=(dict(event,account_id="B"),),bars=rows,account_id="A")


def test_fill_outcome_censors_missing_subminute_market_history():
    rows=[candle(i,100+i) for i in range(15) if i!=4]
    event=dict(account_id="A",executed_at=(
        START+timedelta(minutes=2,seconds=20)).isoformat(),
        inventory_after=.01,action="ADD",instance_id="i1")
    result=fill_price_followthrough(fills=(event,),bars=rows,account_id="A")
    assert len(result)==1
    assert result[0]["signed_future_1m_bps"] is None
    assert result[0]["signed_future_5m_bps"] is None



def test_unobserved_03_boundary_prevents_fake_paper_winner():
    fully=[candle(i,100+i*.1) for i in range(90)]
    complete=market_session_coverage(
        bars=fully,start=START,end=START+timedelta(minutes=90))
    assert complete["comparable"]
    assert complete["coverage_pct"]==100.
    short=[candle(i,100+i*.1) for i in range(12,90)]
    missing_start=market_session_coverage(
        bars=short,start=START,end=START+timedelta(minutes=90))
    assert not missing_start["comparable"]
    assert not missing_start["has_session_start"]
    absent=[candle(i,100+i*.1) for i in range(0,45)]
    missing_end=market_session_coverage(
        bars=absent,start=START,end=START+timedelta(minutes=90))
    assert not missing_end["comparable"]
    assert not missing_end["has_session_end"]
