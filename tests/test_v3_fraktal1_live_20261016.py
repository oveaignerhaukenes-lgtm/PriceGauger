"""Fraktal#1 deterministic SIM-only signal adapter; no broker POST."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from autotrader_open_sizing_v2 import EntryInstrumentRulesV2
from autotrader_v3_fraktal1_v1 import (
    STRATEGY_KEY_V3, FraktalStateV1, causal_closes_v1, fractal_step_v1,
)
from autotrader_v3_fraktal1_bridge_v1 import evaluate_fraktal1_v3
from autotrader_v3_registry_v1 import live_config_issues_v3, sim_config_issues_v3, strategy_v3
from autotrader_v3_strategy_registry_v1 import STRATEGIES_V3, evaluate_strategy_bar_v3
from autotrader_v3_strategy_sizing_v1 import strategy_amount_config_v3
from autotrader_market_rhythm_v1 import ConfirmedTurnV1
from database import connect


START = datetime(2026, 10, 16, 8, 0, tzinfo=timezone.utc)


def price_series(values):
    return pd.Series(
        values, index=pd.date_range(START, periods=len(values), freq="1min")
    )


def source(values):
    return tuple(SimpleNamespace(
        bar_time=(START + timedelta(minutes=i)).isoformat(),
        close=float(v),
    ) for i, v in enumerate(values))


def legal_rules():
    return EntryInstrumentRulesV2(
        uic=4912,asset_type="CfdOnIndex",currency="USD",
        is_tradable=True,non_tradable_reason="None",
        amount_decimals=2,minimum_amount=.01,increment_size=.01,
        contract_size=1.0,supported_order_types=("Market",),
        amount_quantum=.01,reference_minimum_amount=.01,
        minimum_order_value=None,
    )


def test_strategy_registered_as_selectable_unarmed_one_unit():
    spec = strategy_v3("fraktal-1")
    assert spec.runtime_key == STRATEGY_KEY_V3
    assert spec.runtime_ready
    assert STRATEGIES_V3[STRATEGY_KEY_V3].live_route_enabled is False
    live_issues=live_config_issues_v3(strategy_key="fraktal-1",timeframe="1m",control_mode="Manuell",modifiers=())
    assert any("kun SIM/PAPER" in issue for issue in live_issues)
    assert sim_config_issues_v3(strategy_key="fraktal-1",timeframe="1m",control_mode="Manuell",modifiers=())==()
    assert live_config_issues_v3(strategy_key="fraktal-1",timeframe="5m",control_mode="Manuell",modifiers=())
    assert live_config_issues_v3(strategy_key="fraktal-1",timeframe="Adaptiv",control_mode="Manuell",modifiers=())
    sizing=strategy_amount_config_v3(strategy_key=STRATEGY_KEY_V3,rules=legal_rules())
    assert sizing.tranche == pytest.approx(.01)


def test_causal_closed_bars_reject_unclosed_incomplete_and_duplicate():
    data=source([100, 100.5, 101])
    moment=START+timedelta(minutes=2,seconds=5)
    evidence=causal_closes_v1(data,now=moment)
    assert len(evidence)==1 # second bar not past +10s
    evidence=causal_closes_v1(data,now=moment+timedelta(seconds=10))
    assert len(evidence)==2
    doubled=data+(data[-1],)
    assert causal_closes_v1(doubled,now=START+timedelta(minutes=5)).empty


def test_fractal_requires_3_fresh_confirmations_and_exits_flat_first(monkeypatch):
    import autotrader_v3_fraktal1_v1 as mod
    at=START+timedelta(minutes=12)
    prices=pd.Series([100]*13,index=pd.date_range(START,periods=13,freq="1min"))
    call=[]
    def fake_detector(_prices,*,reversal_pct):
        call.append(reversal_pct)
        if reversal_pct==0.05:
            return (ConfirmedTurnV1("TROUGH",prices.index[-2],prices.index[-1],99.,0),)
        if reversal_pct==0.15:
            return (ConfirmedTurnV1("TROUGH",prices.index[-6],prices.index[-5],99.,0),)
        if reversal_pct==0.35:
            return (ConfirmedTurnV1("TROUGH",prices.index[-9],prices.index[-8],98.,0),)
        raise AssertionError(reversal_pct)
    monkeypatch.setattr(mod,"confirmed_turns_v1",fake_detector)
    st=FraktalStateV1(at-timedelta(minutes=1),0.0)
    entry=fractal_step_v1(st,prices=prices,tranche=.01)
    assert entry.action=="FRACTAL_LONG" and entry.state.target_amount==.01
    assert call==[.05,.15,.35]
    assert fractal_step_v1(entry.state,prices=prices,tranche=.01).action=="HOLD_DUPLICATE"
    # A counter micro-swing has to flatten, not directly flip short.
    next_prices=pd.concat([prices,pd.Series([99.6],index=[prices.index[-1]+timedelta(minutes=1)])])
    def reversed_micro(_prices,*,reversal_pct):
        if reversal_pct==.05:
            return (ConfirmedTurnV1("PEAK",next_prices.index[-2],next_prices.index[-1],101.,0),)
        return fake_detector(prices,reversal_pct=reversal_pct)
    monkeypatch.setattr(mod,"confirmed_turns_v1",reversed_micro)
    exit=fractal_step_v1(entry.state,prices=next_prices,tranche=.01)
    assert exit.action=="CONFIRMED_OPPOSITE_FLAT" and exit.state.target_amount==0


def test_no_entry_on_conflict_no_trade_on_discontinuous_bars(monkeypatch):
    import autotrader_v3_fraktal1_v1 as mod
    prices=price_series([100]*12)
    def conflict(p,*,reversal_pct):
        kind="PEAK" if reversal_pct==.35 else "TROUGH"
        return (ConfirmedTurnV1(kind,p.index[-2],p.index[-1],100.,0),)
    monkeypatch.setattr(mod,"confirmed_turns_v1",conflict)
    state=FraktalStateV1(START+timedelta(minutes=10),0.0)
    assert fractal_step_v1(state,prices=prices,tranche=.01).action=="HOLD_SCALE_CONFLICT"
    gap=FraktalStateV1(START+timedelta(minutes=8),0.0)
    assert fractal_step_v1(gap,prices=prices,tranche=.01).action=="HOLD_MISSING_1M"


def test_bootstrap_dedup_switch_and_rejected_expansion_are_safe(tmp_path):
    db=str(tmp_path/"fraktal.sqlite")
    candle=source([100]*100)
    one=evaluate_strategy_bar_v3(
        strategy_key=STRATEGY_KEY_V3,trader_id="live-001",
        observation=SimpleNamespace(timeframe_minutes=1),source_bars=candle,
        actual_inventory=0,signal_timeframe_minutes=1,
        now=START+timedelta(minutes=100,seconds=30),db_path=db)
    assert one.decision.action=="HOLD_BOOTSTRAP" and one.decision.target.amount==0
    again=evaluate_strategy_bar_v3(
        strategy_key=STRATEGY_KEY_V3,trader_id="live-001",
        observation=SimpleNamespace(timeframe_minutes=1),source_bars=candle,
        actual_inventory=0,signal_timeframe_minutes=1,
        now=START+timedelta(minutes=100,seconds=30),db_path=db)
    assert not again.is_new and again.decision.action=="HOLD_DUPLICATE"
    with connect(db,force_sqlite=True) as conn:
        conn.execute("""UPDATE autotrader_v3_fraktal1_state
            SET target_amount=.01 WHERE trader_id=?""",("live-001",))
    later=evaluate_strategy_bar_v3(
        strategy_key=STRATEGY_KEY_V3,trader_id="live-001",
        observation=SimpleNamespace(timeframe_minutes=1),source_bars=source([100]*101),
        actual_inventory=0,signal_timeframe_minutes=1,
        now=START+timedelta(minutes=101,seconds=30),db_path=db)
    assert later.decision.action=="HOLD_BROKER_REALIGN"
    assert later.decision.target.amount==0
    # Separate SIM namespace does not inherit the LIVE position.
    simulation=evaluate_strategy_bar_v3(
        strategy_key=STRATEGY_KEY_V3,trader_id="sim:live-001",
        observation=SimpleNamespace(timeframe_minutes=1),source_bars=source([100]*101),
        actual_inventory=0,signal_timeframe_minutes=1,
        now=START+timedelta(minutes=101,seconds=30),db_path=db)
    assert simulation.decision.action=="HOLD_BOOTSTRAP"


def test_new_policy_never_contains_broker_execution_or_arming():
    policy=Path("autotrader_v3_fraktal1_v1.py").read_text()
    bridge=Path("autotrader_v3_fraktal1_bridge_v1.py").read_text()
    for prohibited in ("SaxoOrderRequest","place_order(","reserve_order_v3","configured_live_pilot_client_v3","set_live_enabled_v3"):
        assert prohibited not in policy and prohibited not in bridge
    live=Path("autotrader_v3_live_runtime_v1.py").read_text()
    # Fraktal#1 is SIM-only: production LIVE does not import its bridge.
    assert "FRAKTAL1_RUNTIME_KEYS_V3" not in live
    assert "if not adapter.live_route_enabled:" in live
    assert "pending_order_v3(" in live
    assert "plan_execution_v3(snapshot)" in live
