"""Histogram Peak Flip regression: symmetric extrema, restart, V3 LIVE routing gate."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from autotrader_macd_dry_run_v2 import MacdObservationV2
from autotrader_open_sizing_v2 import EntryInstrumentRulesV2
from autotrader_v3_closed_bar_driver_v1 import (
    align_closed_bar_target_v3, evaluate_closed_bar_once_v3,
)
from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_histogram_v1 import MacdHistogramConfigV3
from autotrader_v3_macd_histogram_peak_flip_v1 import (
    STRATEGY_KEY_V3, HistogramPeakStateV3,
    histogram_peak_flip_transition_v3, replay_histogram_peak_flip_v3,
)
from autotrader_v3_registry_v1 import (
    strategy_v3, live_config_issues_v3, sim_config_issues_v3,
)
from autotrader_v3_strategy_registry_v1 import STRATEGIES_V3, evaluate_strategy_bar_v3
from autotrader_v3_strategy_sizing_v1 import strategy_amount_config_v3
from database import connect

ZERO=datetime(2026,10,14,9,0,tzinfo=timezone.utc)


def obs(value,i=0):
    return MacdObservationV2(
        bar_time=ZERO + timedelta(minutes=5*i),macd=float(value),signal=0.0)


def run(*values):
    return replay_histogram_peak_flip_v3([obs(x,i) for i,x in enumerate(values)])


def test_negative_histogram_turns_long_then_short_until_exceeds_frozen_peak():
    seq=run(-5,-4,-3,-4,-3.5,-3,-2.8)
    assert [round(x.decision.target.amount,4) for x in seq] == [
        0,.01,.01,-.01,-.01,-.01,.01]
    assert seq[0].decision.action=="HOLD_BOOTSTRAP"
    assert seq[1].state.phase=="NEG_RECOVERY"
    assert seq[2].state.reference==-3
    assert seq[3].state.phase=="NEG_PUSH"
    assert seq[3].state.reference==-3
    assert seq[4].state.reference==-3
    assert seq[5].state.reference==-3  # equal is not above the peak
    assert "BREAK_PREVIOUS_PEAK_LONG" in seq[-1].decision.reason


def test_positive_histogram_mirror_waits_below_previous_trough():
    seq=run(5,4,3,4,3.5,3,2.8)
    assert [round(x.decision.target.amount,4) for x in seq] == [
        0,-.01,-.01,.01,.01,.01,-.01]
    assert seq[2].state.reference==3
    assert seq[3].state.phase=="POS_PUSH"
    assert seq[3].state.reference==3
    assert seq[5].state.reference==3
    assert "BREAK_PREVIOUS_TROUGH_SHORT" in seq[-1].decision.reason


def test_stay_flat_without_correct_initial_recovery_or_cooling():
    seq=run(-1,-2,-3,-4)
    assert all(x.decision.target.amount==0 for x in seq)
    seq=run(1,2,3,4)
    assert all(x.decision.target.amount==0 for x in seq)


def test_zero_crossing_starts_opposite_main_setup_only_on_cooling():
    seq=run(-5,-4,-3,-4,-3.5,-2.8,.2,.1)
    assert [x.state.phase for x in seq[-3:]] == [
        "NEG_RECOVERY","NEG_RECOVERY","POS_COOLING"]
    assert seq[-1].decision.target.amount==-.01
    seq=run(5,4,3,4,3.5,2.8,-.2,-.1)
    assert seq[-1].state.phase=="NEG_RECOVERY"
    assert seq[-1].decision.target.amount==.01


def test_rapid_small_oscillation_without_peak_break_keeps_counter_side():
    seq=run(-5,-4,-3,-4,-3.6,-3.8,-3.5,-3.1,-3.0,-2.99)
    assert all(x.decision.target.amount==-0.01 for x in seq[3:9])
    assert seq[-1].decision.target.amount==.01


def test_no_extra_tranches_and_no_lookahead():
    config=MacdHistogramConfigV3(tranche=.01,max_inventory=.25)
    candles=[-5,-4,-3,-4,-3.4,-3.1,-2.9,-3.2,0.1,0.4,0.3]
    results=replay_histogram_peak_flip_v3(
        [obs(x,i) for i,x in enumerate(candles)],config=config)
    assert all(abs(x.decision.target.amount)<=.01 for x in results)
    for i in range(1,len(candles)):
        prefix=replay_histogram_peak_flip_v3(
            [obs(x,j) for j,x in enumerate(candles[:i])],config=config)
        assert prefix == results[:i]


def test_active_state_requires_finite_threshold_and_valid_phase():
    with pytest.raises(ValueError):
        HistogramPeakStateV3("NEG_PUSH")
    with pytest.raises(ValueError):
        HistogramPeakStateV3("NEG_RECOVERY",float("nan"))
    with pytest.raises(ValueError):
        HistogramPeakStateV3("bogus",1)
    with pytest.raises(ValueError):
        HistogramPeakStateV3("WAIT",1)


def test_driver_restarts_retain_peak_and_duplicate_bar_cannot_flip_twice(tmp_path):
    path=str(tmp_path/"hist-peak.db")
    trader="sim-hist-peak-1"
    for i,value in enumerate((-5,-4,-3,-4,-3.5,-3,-2.8)):
        r=evaluate_strategy_bar_v3(
            strategy_key=STRATEGY_KEY_V3,trader_id=trader,
            observation=obs(value,i),db_path=path)
        assert r.is_new
        expected=(0,.01,.01,-.01,-.01,-.01,.01)[i]
        assert r.decision.target.amount==pytest.approx(expected)
        dupe=evaluate_strategy_bar_v3(
            strategy_key=STRATEGY_KEY_V3,trader_id=trader,
            observation=obs(value,i),db_path=path)
        assert not dupe.is_new
        assert dupe.decision.action=="HOLD_DUPLICATE"
        with connect(path,force_sqlite=True) as db:
            state=db.execute(
                "SELECT last_bar_time,phase,reference_level "
                "FROM autotrader_v3_histogram_peak_state WHERE trader_id=?",
                (trader,)).fetchone()
            assert state["last_bar_time"]==obs(value,i).bar_time.isoformat()
            assert state["phase"]==(
                "WAIT","NEG_RECOVERY","NEG_RECOVERY","NEG_PUSH",
                "NEG_PUSH","NEG_PUSH","NEG_RECOVERY")[i]


def test_outside_inventory_alignment_discards_old_breakout_level(tmp_path):
    path=str(tmp_path/"align-peak.db")
    trader="peak-align"
    for i,value in enumerate((-5,-4,-3,-4)):
        evaluate_closed_bar_once_v3(
            strategy_key=STRATEGY_KEY_V3,trader_id=trader,
            observation=obs(value,i),db_path=path)
    assert align_closed_bar_target_v3(
        trader_id=trader,target_amount=0,db_path=path)
    with connect(path,force_sqlite=True) as db:
        row=db.execute(
            "SELECT phase,reference_level FROM autotrader_v3_histogram_peak_state "
            "WHERE trader_id=?",(trader,)).fetchone()
        assert row["phase"]=="WAIT" and row["reference_level"] is None
    r=evaluate_closed_bar_once_v3(
        strategy_key=STRATEGY_KEY_V3,trader_id=trader,
        observation=obs(-3.4,4),db_path=path)
    assert r.decision.target.amount==0
    assert r.decision.action=="HOLD_BOOTSTRAP"


def test_instances_do_not_share_thresholds(tmp_path):
    path=str(tmp_path/"many-peaks.db")
    for trader,points in (("a",(-5,-4,-3,-4)),("b",(5,4,3,4))):
        for i,value in enumerate(points):
            evaluate_strategy_bar_v3(
                strategy_key=STRATEGY_KEY_V3,trader_id=trader,
                observation=obs(value,i),db_path=path)
    with connect(path,force_sqlite=True) as db:
        rows=db.execute(
            "SELECT trader_id,phase,reference_level "
            "FROM autotrader_v3_histogram_peak_state ORDER BY trader_id"
        ).fetchall()
        assert [(x["trader_id"],x["phase"],x["reference_level"]) for x in rows]==[
            ("a","NEG_PUSH",-3),("b","POS_PUSH",3)]


def test_registers_sim_and_live_with_legal_tech100_tranche():
    assert STRATEGY_KEY_V3 in STRATEGIES_V3
    assert STRATEGIES_V3[STRATEGY_KEY_V3].live_route_enabled is True
    spec=strategy_v3("macd-histogram-peak-flip")
    assert spec.runtime_key==STRATEGY_KEY_V3
    assert "Peak Flip" in spec.label
    assert sim_config_issues_v3(
        strategy_key="macd-histogram-peak-flip",timeframe="2m",
        control_mode="Manuell",modifiers=())==()
    assert live_config_issues_v3(
        strategy_key="macd-histogram-peak-flip",timeframe="2m",
        control_mode="Manuell",modifiers=()) == ()
    rules=EntryInstrumentRulesV2(
        uic=4912,asset_type="CfdOnIndex",currency="USD",
        is_tradable=True,non_tradable_reason="None",amount_decimals=2,
        minimum_amount=.01,increment_size=.01,contract_size=1,
        supported_order_types=("Market",),amount_quantum=.01,
        reference_minimum_amount=.01,minimum_order_value=None)
    cfg=strategy_amount_config_v3(strategy_key=STRATEGY_KEY_V3,rules=rules)
    assert cfg.tranche==.01


def test_pure_module_cannot_arm_live_or_send_orders():
    source=Path("autotrader_v3_macd_histogram_peak_flip_v1.py").read_text()
    for forbidden in ("configured_live_pilot_client_v3","from database import",
                      "place_order(","set_live_enabled","SaxoOrderRequest"):
        assert forbidden not in source
