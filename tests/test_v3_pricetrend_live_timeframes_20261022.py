"""PriceTrend 1m–1h guarded V3 LIVE readiness, source causality and UI contract.

Offline tests only. Never send Saxo orders or change live account state.
"""
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from pathlib import Path

import pytest

from autotrader_v3_pricetrend_v1 import (
    STRATEGY_KEY_V3, BASELINE_KEY_V3, SUPPORTED_SIGNAL_MINUTES,
    _aggregate, _closed_source, pricetrend_target_v1,
)
from autotrader_v3_registry_v1 import (
    LIVE_TIMEFRAMES_V3, live_config_issues_v3, sim_config_issues_v3
)
from autotrader_v3_strategy_registry_v1 import strategy_adapter_v3
from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_histogram_v1 import MacdHistogramConfigV3

START=datetime(2026,10,21,0,0,tzinfo=timezone.utc)

def make_bars(n=840):
    result=[]
    prev=30000.
    for i in range(n):
        close=30000.-.85*i+.16*((i%7)-3)
        result.append(SimpleNamespace(
            bar_time=START+timedelta(minutes=i),
            market_name="US Tech 100 NAS",open=prev,
            high=max(close,prev)+.6,low=min(close,prev)-.6,
            close=close,volume=None))
        prev=close
    return result

def obs(minute):
    return SimpleNamespace(
        closed_at=START+timedelta(minutes=minute),
        bar_time=START+timedelta(minutes=minute-1),spread=0.)



@pytest.mark.parametrize("minutes", SUPPORTED_SIGNAL_MINUTES)
def test_every_fixed_v3_period_uses_genuinely_closed_signal_bar(minutes):
    bars=make_bars(840)
    target=TargetInventoryV3(0)
    decide=lambda source: pricetrend_target_v1(
        current_target=target, observation=obs(840),
        source_bars=source,market_name="US Tech 100 NAS",
        signal_timeframe_minutes=minutes,
        config=MacdHistogramConfigV3(tranche=.01,max_inventory=.01))
    first=decide(bars)
    assert first.action=="OPEN_SHORT"
    assert first.target.amount==-.01
    assert first.reason.count("S%d"%minutes)==1
    # A future 1m bar must not change a decision at the prior completed S bar.
    future=make_bars(850)
    assert decide(future)==first
    # At a complete 1m instant, but not an S-close (except 1m), fail closed.
    if minutes>1:
        wrong=pricetrend_target_v1(
            current_target=target,observation=obs(841),
            source_bars=make_bars(841),market_name="US Tech 100 NAS",
            signal_timeframe_minutes=minutes)
        assert wrong.action=="FLAT_DATA_GAP"


@pytest.mark.parametrize("tf", LIVE_TIMEFRAMES_V3)
def test_v3_fixed_timeframes_supported_without_auto_arming(tf):
    issues=live_config_issues_v3(
        strategy_key="pricetrend-1",timeframe=tf,
        control_mode="Manuell",modifiers=())
    assert not issues, (tf,issues)
    assert not sim_config_issues_v3(
        strategy_key="pricetrend-1",timeframe=tf,
        control_mode="Manuell",modifiers=())
    assert strategy_adapter_v3(STRATEGY_KEY_V3).live_route_enabled
    assert not strategy_adapter_v3(BASELINE_KEY_V3).live_route_enabled


def test_adaptive_period_and_sma_baseline_rejected_from_live():
    assert live_config_issues_v3(
        strategy_key="pricetrend-1",timeframe="Adaptiv",
        control_mode="Manuell",modifiers=())
    assert live_config_issues_v3(
        strategy_key="sma-9-21-baseline",timeframe="2m",
        control_mode="Manuell",modifiers=())


def test_real_product_account_and_size_guards_are_upstream_of_broker():
    src=Path("autotrader_v3_live_runtime_v1.py").read_text()
    assert "int(e.uic)!=PRICETREND_TECH100_UIC" in src
    assert "str(e.asset_type)!=PRICETREND_TECH100_ASSET" in src
    assert "abs(actual.amount)>float(strategy_amount_config.tranche)" in src
    assert "live_authority_armed_v3" in src
    assert "pending_order_v3(" in src
    assert "reconcile_position_v3(" in src
    assert "broker.precheck(order)" in src
    assert "reserve_order_v3(" in src
    assert "broker.place_order(order,confirm_live=True)" in src


def test_signal_timeframe_flows_through_live_driver_and_paper_replay():
    driver=Path("autotrader_v3_closed_bar_driver_v1.py").read_text()
    reg=Path("autotrader_v3_strategy_registry_v1.py").read_text()
    runtime=Path("autotrader_v3_live_runtime_v1.py").read_text()
    replay=Path("strategy_lab_v2_replay.py").read_text()
    assert 'extra["signal_timeframe_minutes"] = int(signal_timeframe_minutes)' in driver
    assert 'extras=' in reg
    assert 'if e.strategy_key==PRICETREND_KEY else {}' in runtime
    assert 'args["signal_timeframe_minutes"]=signal_timeframe_minutes' in replay
    assert "source=segment[max(0,ix-840):ix+1]" in replay


@pytest.mark.parametrize("tf", ["1m","5m","10m"])
def test_replay_uses_real_next_bar_and_charges_costs_on_variable_periods(tf):
    from strategy_lab_v2_replay import ReplayCostsV2, replay_v3_strategy_v2
    periods=int(tf[:-1])
    length=max(510,periods*45+65)
    length=min(length,840)
    costs=ReplayCostsV2(
        point_value_nok=1.,spread_bps=1.5,variable_fee_bps=.8,
        fixed_fee_nok=.15,starting_nav_nok=10000,
        lot_step=.01,max_lots=.01)
    result=replay_v3_strategy_v2(
        strategy_key="pricetrend-1",bars=make_bars(length),
        costs=costs,timeframe=tf)
    assert result.trades>=1
    assert result.total_cost_nok>0
