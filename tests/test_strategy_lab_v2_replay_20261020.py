"""Strategy Lab v2 provenance: pure replay, 1m next-open fills, account scope."""
from dataclasses import replace
from datetime import datetime,timedelta,timezone
from math import sin
from pathlib import Path
from types import SimpleNamespace
import json

import pytest

from strategy_lab_v2_replay import (
    ReplayCostsV2,PURE_V3,MAX_BARS,
    strategy_catalog_v2,replay_v3_strategy_v2,
)
from strategy_lab_v2_ai import (
    build_lab_asof_evidence_v2,lab_ai_evidence_fingerprint_v2,ask_lab_ai_v2,
)

START=datetime(2026,10,19,9,tzinfo=timezone.utc)


def feed(length=280,*,gap_at=None,price_jump=0):
    rows=[]
    for i in range(length):
        minute=i+(10 if gap_at is not None and i>=gap_at else 0)
        stamp=START+timedelta(minutes=minute)
        p=100+5*sin(i/12)+i*.012
        if i>120:p+=price_jump
        op=p-.15
        rows.append(SimpleNamespace(
            bar_time=stamp.isoformat(),market_name="US Tech100",
            open=op,high=max(op,p)+.2,low=min(op,p)-.2,
            close=p,volume=100,quality_flags=1))
    return tuple(rows)


COST=ReplayCostsV2(point_value_nok=12.,spread_bps=8.,
                    variable_fee_bps=2.,fixed_fee_nok=2.,
                    lot_step=.01,max_lots=.03,starting_nav_nok=1000.)


def test_all_catalog_visible_but_only_supported_true_replay():
    families=strategy_catalog_v2()
    items=[x for group in families.values() for x in group]
    assert len(items)>=20
    assert {x["key"] for x in items if x["replay_ready"]}==set(PURE_V3)
    assert next(x for x in items if x["key"]=="aen-core-auto")["replay_ready"] is False
    with pytest.raises(ValueError,match="not yet replay-ready"):
        replay_v3_strategy_v2(
            strategy_key="aen-core-auto",bars=feed(),costs=COST)


def test_replay_actual_macd_function_and_fills_are_next_real_open():
    result=replay_v3_strategy_v2(
        strategy_key="macd-histogram",bars=feed(),costs=COST,timeframe="2m")
    assert len(result.points)==280
    assert result.events
    assert result.trades>0
    for event in result.events:
        assert event.at in {START+timedelta(minutes=i) for i in range(280)}
        assert event.at>result.points[0].at-timedelta(minutes=1)
        assert event.cost_nok>=COST.fixed_fee_nok
    assert result.total_cost_nok>0
    assert result.cost_source=="MANUAL_SCENARIO"
    assert all(-.031<=p.lots<=.031 for p in result.points)


def test_next_bar_event_not_timestamped_on_trigger_candle():
    result=replay_v3_strategy_v2(
        strategy_key="macd-flip",bars=feed(),costs=COST,timeframe="2m")
    for event in result.events:
        if event.kind=="GAP_FLAT":continue
        assert event.at.second==0
        assert event.at.minute%2 in (0,1)
    assert result.points[0].lots==0


def test_no_lookahead_prefix_same_when_future_bars_appended():
    shorter=replay_v3_strategy_v2(
        strategy_key="macd-flip",bars=feed(225),costs=COST,timeframe="2m")
    longer=replay_v3_strategy_v2(
        strategy_key="macd-flip",bars=feed(280),costs=COST,timeframe="2m")
    assert [p.lots for p in shorter.points]==[p.lots for p in longer.points[:225]]
    assert [p.signal for p in shorter.points]==[p.signal for p in longer.points[:225]]
    assert [p.nav_nok for p in shorter.points]==pytest.approx(
        [p.nav_nok for p in longer.points[:225]])


def test_discontinuity_cancel_pending_and_no_cross_gap_return():
    result=replay_v3_strategy_v2(
        strategy_key="macd-histogram",bars=feed(280,gap_at=170),
        costs=COST,timeframe="2m")
    assert result.skipped_gaps==1
    prior=replay_v3_strategy_v2(
        strategy_key="macd-histogram",bars=feed(170),
        costs=COST,timeframe="2m")
    if prior.points[-1].lots:
        assert any(e.kind=="GAP_FLAT" for e in result.events)
    else:
        assert not any(e.kind=="GAP_FLAT" for e in result.events)
    first_after=next(p for p in result.points
                     if p.at>=START+timedelta(minutes=180))
    assert first_after.lots==0
    assert all(e.kind!="OPEN" or e.at!=START+timedelta(minutes=180)
               for e in result.events)


def test_no_zero_cost_or_nonfinite_configuration():
    for change in ({"point_value_nok":0},
                   {"spread_bps":-1},
                   {"fixed_fee_nok":-2},
                   {"max_lots":.001}):
        with pytest.raises(ValueError):
            replace(COST,**change)


def test_price_plus_macd_requires_exact_signal_clock():
    with pytest.raises(ValueError,match="require 1m"):
        replay_v3_strategy_v2(
            strategy_key="precross-price-1m-macd2m",
            bars=feed(),costs=COST,timeframe="2m")


def test_ai_cursor_never_includes_future_bar_or_future_fill():
    result=replay_v3_strategy_v2(
        strategy_key="macd-histogram",bars=feed(),costs=COST,timeframe="2m")
    index=180
    cursor=result.points[index].at
    evidence=build_lab_asof_evidence_v2(
        strategy="macd-histogram",selected_at=cursor,
        points=result.points,events=result.events,
        market="US Tech100",product_key="4912",
        costs_source=result.cost_source)
    assert evidence["source"]=="STRATEGY_LAB_V2_PAPER_ASOF"
    assert all(datetime.fromisoformat(x["time"])<=cursor
               for x in evidence["closed_prices"])
    assert all(datetime.fromisoformat(x["time"])<=cursor
               for x in evidence["past_paper_trades"])
    assert len(evidence["closed_prices"])<=24
    assert len(lab_ai_evidence_fingerprint_v2(evidence))==64
    with pytest.raises(ValueError,match="as-of"):
        ask_lab_ai_v2(evidence={"source":"BAD"},question="What?",
                      key="fake",post=lambda *a,**k:None)


def test_ai_can_only_chat_on_explicit_button_and_not_place_trades():
    page=Path("pages/0_Strategy_Lab_V2.py").read_text()
    source=Path("strategy_lab_v2_replay.py").read_text()
    ai=Path("strategy_lab_v2_ai.py").read_text()
    nav=Path("navigation_config.py").read_text()
    assert "Strategilab v2" in nav
    assert "Kontoprestasjon" in page
    assert "Eksporter komplett replay til ChatGPT" in page
    assert "Analyser valgt tidspunkt med AI" in page
    assert "Spol: ferdig 1m-observasjon" in page
    assert "create_trade" not in ai
    for forbidden in ("place_order(","_post(","set_live_enabled_v3(",
                      "evaluate_closed_bar_once_v3(","save_autotrader_config_v3("):
        assert forbidden not in source
        assert forbidden not in ai
