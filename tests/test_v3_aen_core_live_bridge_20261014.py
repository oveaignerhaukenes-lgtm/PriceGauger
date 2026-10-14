"""AEn Core V3 LIVE capability: closed 1m inputs, one legal unit, no stale re-entry."""
from __future__ import annotations

from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from pathlib import Path

import pytest

from aen_replay_v1 import AEnPaperConfig, Indicator
from aen_core_v1 import StructureEvent
from autotrader_v3_aen_core_bridge_v1 import (
    AEN_CORE_KEYS_V3,AEN_CORE_PRESETS_V3,AEnV3State,
    aen_core_step_v3,evaluate_aen_core_v3,ensure_aen_v3_schema,
)
from autotrader_v3_closed_bar_driver_v1 import align_closed_bar_target_v3
from autotrader_v3_registry_v1 import (
    STRATEGIES_V3 as CATALOG,live_config_issues_v3,sim_config_issues_v3,
)
from autotrader_v3_strategy_registry_v1 import (
    STRATEGIES_V3, evaluate_strategy_bar_v3,
)
from autotrader_v3_strategy_sizing_v1 import strategy_amount_config_v3
from autotrader_open_sizing_v2 import EntryInstrumentRulesV2
from database import connect

BASE=datetime(2026,10,14,10,0,tzinfo=timezone.utc)


def indicator(i,h=.3,old=.1,k=75,d=65):
    return Indicator(BASE+timedelta(minutes=i),h,old,k,d)


def event(kind,level=99):
    return StructureEvent(kind,1,2,level)


def config(family="MACD Hold",minutes=1,adaptive=False):
    return AEnPaperConfig(family=family,minutes=minutes,structure_minutes=5,
                          max_units=1,adaptive=adaptive,structure_scaling=False)


def state(i=0,amount=0,**kw):
    return AEnV3State((BASE+timedelta(minutes=i)).isoformat(),amount,1,**kw)


def step(s,i,events=(),h=.3,prev=.1,close=100):
    return aen_core_step_v3(state=s,config=config(),at=BASE+timedelta(minutes=i),
                            indicator_sets={1:{BASE+timedelta(minutes=i):
                                        indicator(i,h,prev)}},
                            events=events,tranche=.01,bar_close=close)


def bars(n=500):
    return tuple(SimpleNamespace(
        bar_time=(BASE+timedelta(minutes=i)).isoformat(),
        open=100.,high=100.5,low=99.5,close=100.,volume=20.,
    ) for i in range(n))


def rules():
    return EntryInstrumentRulesV2(
        uic=4912,asset_type="CfdOnIndex",currency="USD",
        is_tradable=True,non_tradable_reason="None",
        amount_decimals=2,minimum_amount=.01,increment_size=.01,
        contract_size=1.0,supported_order_types=("Market",),
        amount_quantum=.01,reference_minimum_amount=.01,
        minimum_order_value=None)


def test_all_five_frozen_families_live_selectable_without_arming():
    assert set(AEN_CORE_PRESETS_V3)==AEN_CORE_KEYS_V3
    assert len(AEN_CORE_KEYS_V3)==5
    assert {x.runtime_key for x in CATALOG if x.key.startswith("aen-core-")}==AEN_CORE_KEYS_V3
    for item in CATALOG:
        if item.key.startswith("aen-core-"):
            assert item.runtime_ready
            assert STRATEGIES_V3[item.runtime_key].live_route_enabled
            assert live_config_issues_v3(strategy_key=item.key,timeframe="10m",
                control_mode="Manuell",modifiers=())==()
            assert sim_config_issues_v3(strategy_key=item.key,timeframe="5m",
                control_mode="Manuell",modifiers=())==()
            assert "1-enhet" in item.description or "én enhet" in item.description or "én Saxo" in item.description
            bad=live_config_issues_v3(strategy_key=item.key,timeframe="1h",
                control_mode="Manuell",modifiers=())
            assert bad and "AEn Core" in str(bad)
            assert live_config_issues_v3(strategy_key=item.key,timeframe="Adaptiv",
                control_mode="Manuell",modifiers=())


def test_instrument_sizing_uses_saxo_legal_unit_for_all_variants():
    for runtime in AEN_CORE_KEYS_V3:
        amount=strategy_amount_config_v3(strategy_key=runtime,rules=rules())
        assert amount.tranche==pytest.approx(.01)
        assert amount.max_inventory>=.01
    # The bridge, independent of V3 generic max_inventory, can output only
    # +/- exactly one legal amount, never the generic ten-tranche cap.


def test_causal_confirmed_HH_HL_one_unit_and_opposite_structure_flat():
    a=step(state(),1,(event("HH",102),))
    assert a.state.arm=="LONG" and a.state.target_amount==0
    b=step(a.state,2,(event("HL",97),))
    assert b.reason=="HH_HL_OPEN"
    assert b.state.target_amount==.01 and b.state.protected_level==97
    c=step(b.state,3,(event("LL",96),),h=.3,prev=.1,close=100)
    assert c.state.target_amount==.01 and c.state.active_break
    d=step(c.state,4,(event("LH",100),),h=.3,prev=.1,close=100)
    assert d.reason=="STRUCTURE_LH_FLAT" and d.state.target_amount==0
    assert d.state.protected_level is None


def test_protected_swing_and_macd_reversal_flat_never_flip_directly():
    s=state(amount=.01,arm="LONG",protected_level=98)
    out=step(s,1,close=97)
    assert out.reason=="PROTECTED_SWING_FLAT"
    assert out.state.target_amount==0
    s=state(amount=.01,arm="LONG")
    out=step(s,1,h=-.2,prev=.1)
    assert out.reason=="MACD_REVERSE_FLAT" and out.state.target_amount==0
    # AEn must not open SHORT from an existing LONG on a single signal.
    assert all(abs(x.state.target_amount)<=.01 for x in (out,))


def test_canonical_missing_minute_does_not_replay_stale_signal():
    s=state(0,amount=.01,arm="LONG",protected_level=98)
    out=step(s,3,(event("LL"),),h=-.1,prev=.2)
    assert out.reason=="HOLD_MISSING_1M"
    assert out.state.target_amount==.01
    assert out.state.arm=="HOLD"
    assert step(out.state,3).reason=="HOLD_DUPLICATE"


def test_macd_histogram_hysteresis_stoch_are_distinct_regime_filters():
    from aen_replay_v1 import _desired_regime
    obs=indicator(1,h=-.5,old=-.7,k=20,d=10)
    assert _desired_regime(config("MACD Histogram"),obs)=="LONG"
    assert _desired_regime(config("MACD Hold"),obs)=="SHORT"
    assert _desired_regime(config("MACD + Stochastic"),obs)=="HOLD"
    shy=indicator(1,h=.1,old=.8,k=50,d=40)
    assert _desired_regime(config("MACD Hysteresis"),shy)=="HOLD"


def test_v3_bootstrap_dedup_and_context_switch_uses_no_historical_orders(tmp_path):
    db=str(tmp_path/"aen-v3.sqlite")
    prices=bars(200)
    one=evaluate_strategy_bar_v3(
        strategy_key="aen-core-hold-v1",trader_id="account-a",
        observation=SimpleNamespace(timeframe_minutes=5),source_bars=prices,
        actual_inventory=0,signal_timeframe_minutes=5,
        now=BASE+timedelta(minutes=200,seconds=30),db_path=db)
    assert one.is_new and one.decision.action=="HOLD_BOOTSTRAP"
    assert one.decision.target.amount==0
    duplicate=evaluate_strategy_bar_v3(
        strategy_key="aen-core-hold-v1",trader_id="account-a",
        observation=SimpleNamespace(timeframe_minutes=5),source_bars=prices,
        actual_inventory=0,signal_timeframe_minutes=5,
        now=BASE+timedelta(minutes=200,seconds=30),db_path=db)
    assert not duplicate.is_new and duplicate.decision.target.amount==0
    assert duplicate.decision.action=="HOLD_DUPLICATE"
    later=evaluate_strategy_bar_v3(
        strategy_key="aen-core-hold-v1",trader_id="account-a",
        observation=SimpleNamespace(timeframe_minutes=5),source_bars=bars(201),
        actual_inventory=0,signal_timeframe_minutes=5,
        now=BASE+timedelta(minutes=201,seconds=30),db_path=db)
    assert later.is_new and abs(later.decision.target.amount)<=.01
    changed=evaluate_strategy_bar_v3(
        strategy_key="aen-core-histogram-v1",trader_id="account-a",
        observation=SimpleNamespace(timeframe_minutes=5),source_bars=bars(201),
        actual_inventory=.01,signal_timeframe_minutes=5,
        now=BASE+timedelta(minutes=201,seconds=30),db_path=db)
    assert changed.decision.action=="HOLD_BOOTSTRAP"
    assert changed.decision.target.amount==.01


def test_risk_alignment_without_legacy_state_resets_aen_memory(tmp_path):
    db=str(tmp_path/"aen-align.sqlite")
    ensure_aen_v3_schema(db)
    with connect(db,force_sqlite=True) as con:
        con.execute("""INSERT INTO autotrader_v3_aen_core_state(
            trader_id,context_key,last_bar_end,target_amount,signal_minutes,
            arm,active_break,cooling_count,strength_count)
            VALUES(?,?,?,?,?,?,?,?,?)""",
            ("aen-align","aen-core-hold-v1:S5:structure5:one-unit",
             BASE.isoformat(),.01,5,"LONG",0,0,0))
    assert align_closed_bar_target_v3(
        trader_id="aen-align",target_amount=0,db_path=db)
    with connect(db,force_sqlite=True) as con:
        assert con.execute(
            "SELECT * FROM autotrader_v3_aen_core_state WHERE trader_id=?",
            ("aen-align",)).fetchone() is None


def test_no_live_enable_or_order_submission_in_bridge_and_worker_gates():
    module=Path("autotrader_v3_aen_core_bridge_v1.py").read_text()
    for forbidden in ("configured_live_pilot_client_v3","SaxoOrderRequest",
                      "place_order(","set_live_enabled","live_authority_armed_v3"):
        assert forbidden not in module
    worker=Path("autotrader_v3_live_runtime_v1.py").read_text()
    assert "if not adapter.live_route_enabled" in worker
    assert "pending_order_v3(" in worker
    assert "reserve_order_v3(" in worker
    assert "plan_execution_v3(snapshot)" in worker
    assert "signal_timeframe_minutes" in worker
