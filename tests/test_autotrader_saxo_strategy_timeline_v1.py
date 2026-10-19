"""Saxo account graph is timestamp-accurate and strategy attribution stays honest."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from autotrader_saxo_strategy_timeline_v1 import (
    build_saxo_account_strategy_chart_v1, strategy_periods_from_snapshots_v1,
    MAX_GAP_SECONDS,
)

ZERO=datetime(2026,10,19,12,0,tzinfo=timezone.utc)


def snap(minute,*,strategy="macd-stoch-v2",armed=True,account="A",
         currency="NOK",quality="Ok",value=1000.,market="Tech100",
         contexts=None):
    if contexts is None:
        contexts=[{
            "instance_id":"trader-A", "strategy":strategy,
            "timeframe":"1m", "regime_timeframe":"15m",
            "market":market,"market_bar_at":ZERO.isoformat(),
            "live_armed":armed,
        }]
    return {
        "observed_at":(ZERO+timedelta(minutes=minute)).isoformat(),
        "account_id":account,"account_name":"Tech100-A",
        "currency":currency,"total_value":value,
        "calculation_reliability":quality,
        "context_json":json.dumps(contexts),
    }


def test_two_strategies_have_distinct_as_of_periods_not_backfilled_from_current_config():
    seq=[
        snap(0,strategy="macd-stoch-v2"),
        snap(5,strategy="macd-stoch-v2",value=1010),
        snap(10,strategy="macd-stoch-rhythm-build",value=1020),
        snap(15,strategy="macd-stoch-rhythm-build",value=1030),
    ]
    periods=strategy_periods_from_snapshots_v1(seq)
    assert len(periods)==2
    assert [p.strategy_key for p in periods]==[
        "macd-stoch-v2","macd-stoch-rhythm-build"]
    assert [p.first_observed for p in periods]==[
        ZERO,ZERO+timedelta(minutes=10)]
    assert [p.last_observed for p in periods]==[
        ZERO+timedelta(minutes=5),ZERO+timedelta(minutes=15)]
    assert [p.observations for p in periods]==[2,2]


def test_no_claim_about_exact_switch_time_and_no_bridge_across_missing_telemetry():
    seq=[snap(0),snap(5),snap(40),snap(45,strategy="fraktal-1")]
    periods=strategy_periods_from_snapshots_v1(seq)
    assert len(periods)==3
    assert periods[0].last_observed==ZERO+timedelta(minutes=5)
    assert periods[1].first_observed==ZERO+timedelta(minutes=40)
    assert periods[1].last_observed==ZERO+timedelta(minutes=40)
    fig,valid,_=build_saxo_account_strategy_chart_v1(seq)
    assert valid==4
    assert fig.data[0].y == (1000.,1000.,None,1000.,1000.)


def test_no_false_profit_curve_when_saxo_quality_is_unverified():
    samples=[snap(0),snap(5,quality="StalePrice",value=2000),snap(10)]
    fig,valid,periods=build_saxo_account_strategy_chart_v1(samples)
    assert valid==2
    assert fig.data[0].y==(1000.,None,1000.)
    assert len(periods)==1
    assert fig.layout.yaxis.title.text=="Kontoverdi (NOK)"
    assert "Tid (UTC)" in fig.layout.xaxis2.title.text


def test_off_instance_is_visually_not_the_active_strategy():
    seq=[snap(0,armed=False),snap(5,armed=False),snap(10,armed=True)]
    periods=strategy_periods_from_snapshots_v1(seq)
    assert len(periods)==2
    assert periods[0].live_armed is False
    assert periods[0].label.startswith("AV · ")
    assert periods[1].live_armed is True


def test_manual_only_account_and_multiple_live_owners_do_not_get_false_strategy():
    manual=[snap(0,contexts=[])]
    ambiguous=[snap(5,contexts=[
        {"instance_id":"A","strategy":"macd","live_armed":True},
        {"instance_id":"B","strategy":"stoch","live_armed":True},
    ])]
    observed=strategy_periods_from_snapshots_v1(manual+ambiguous)
    assert observed[0].label=="Ingen registrert LIVE-strategi"
    assert observed[1].label=="Flere LIVE-instanser · ukjent"
    assert observed[1].live_armed is False


def test_account_or_currency_cannot_be_cross_joined():
    for other in (snap(5,account="B"),snap(5,currency="USD")):
        with pytest.raises(ValueError,match="cannot mix Saxo account/currency"):
            strategy_periods_from_snapshots_v1([snap(0),other])


def test_gaps_do_not_draw_continuous_account_values():
    assert MAX_GAP_SECONDS>300
    fig,valid,periods=build_saxo_account_strategy_chart_v1([
        snap(0,value=1000),snap(20,value=1100),
    ])
    assert valid==2 and len(periods)==2
    assert fig.data[0].x[1] is None
    assert fig.data[0].y[1] is None
    # Single observations are markers instead of fabricated duration bands.
    assert all(p.first_observed==p.last_observed for p in periods)


def test_active_account_charts_in_ui_instead_of_only_selected_account_graph():
    page=Path("pages/0_Kontostatistikk.py").read_text(encoding="utf-8")
    assert "for account_id in visible_account_ids:" in page
    assert "load_v3_instances_v1()" in page
    assert "load_account_truth_v1(account_id=account_id,days=days)" in page
    assert "build_saxo_account_strategy_chart_v1" in page
    assert "Observerte strategiperioder" in page
    assert "Vis også Saxo-kontoer" in page
