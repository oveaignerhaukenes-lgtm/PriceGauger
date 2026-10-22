"""PriceTrend #1 causal SIM strategy and SMA9/21 benchmark for Tech100."""
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from pathlib import Path

import pytest

from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_histogram_v1 import MacdHistogramConfigV3
from autotrader_v3_pricetrend_v1 import (
    STRATEGY_KEY_V3,BASELINE_KEY_V3,
    price_regime_v1,pricetrend_target_v1,sma_9_21_baseline_target_v1,
    _aggregate,_closed_source,
)
from autotrader_v3_registry_v1 import (
    strategy_v3,live_config_issues_v3,sim_config_issues_v3
)
from autotrader_v3_strategy_registry_v1 import strategy_adapter_v3
from strategy_lab_v2_replay import (
    PURE_V3,ReplayCostsV2,replay_v3_strategy_v2
)

START=datetime(2026,10,21,0,0,tzinfo=timezone.utc)


def make_bars(n=260, *,direction=-1, market="US Tech 100 NAS"):
    out=[]
    previous=30000.
    for i in range(n):
        wave=0.16*((i%7)-3)
        close=30000+direction*0.85*i+wave
        op=previous
        out.append(SimpleNamespace(
            bar_time=START+timedelta(minutes=i),market_name=market,
            open=op,high=max(op,close)+0.6,
            low=min(op,close)-0.6,close=close,volume=None))
        previous=close
    return out


def obs(n,spread=0.):
    return SimpleNamespace(closed_at=START+timedelta(minutes=n),
        bar_time=START+timedelta(minutes=n-2),spread=spread)


def decide(bars, *,now=None,current=0, func=pricetrend_target_v1,
           market="US Tech 100 NAS",spread=0):
    n=now or len(bars)
    return func(current_target=TargetInventoryV3(current),
                observation=obs(n,spread),
                source_bars=bars,market_name=market,
                config=MacdHistogramConfigV3(tranche=.01,max_inventory=.03))


def test_clean_overnight_downtrend_opens_and_holds_short_despite_macd_flip():
    bars=make_bars(260,direction=-1)
    first=decide(bars,spread=+12.)
    assert first.action=="OPEN_SHORT"
    assert first.target.amount==-.01
    second=decide(bars,spread=-17.,current=-.01)
    assert second.action=="HOLD_SHORT"
    assert second.target.amount==-.01
    opposite=make_bars(260,direction=+1)
    assert decide(opposite).action=="OPEN_LONG"


def test_price_first_exit_on_large_counter_move_before_macd_confirmation():
    bars=make_bars(254,direction=-1)
    prev=bars[-1].close
    for i in range(254,260):
        close=prev+11.
        bars.append(SimpleNamespace(
            bar_time=START+timedelta(minutes=i),
            market_name="US Tech 100 NAS",open=prev,
            high=close+0.5,low=prev-0.5,close=close,volume=None))
        prev=close
    decision=decide(bars,current=-.01,spread=-45.)
    assert decision.action=="EXIT_SHORT"
    assert decision.target.amount==0
    assert "ATR" in decision.reason


def test_no_lookahead_partial_5m_or_future_bar():
    full=make_bars(262)
    at260=decide(full,now=260)
    at260_prefix=decide(full[:260],now=260)
    assert at260==at260_prefix
    # Completed 2m bar at 262, but only two minutes of the next 5m:
    assert len(_aggregate(_closed_source(full,START+timedelta(minutes=262)),5))>=24


@pytest.mark.parametrize("bad",["gap","duplicate","stale","nan"])
def test_invalid_1m_feed_flattens_and_never_opens(bad):
    bars=make_bars(260)
    if bad=="gap":
        bars.pop(190)
    elif bad=="duplicate":
        bars.append(bars[-2])
    elif bad=="stale":
        bars.pop()
    else:
        bars[-1].close=float("nan")
    result=decide(bars,now=260,current=-.01)
    assert result.action=="FLAT_DATA_GAP"
    assert result.target.amount==0


def test_missing_warmup_and_other_market_fail_closed():
    bars=make_bars(80)
    assert decide(bars,current=0).target.amount==0
    silver=make_bars(260,market="Silver")
    response=decide(silver,current=0,market="Silver")
    assert response.action=="FLAT_OTHER_MARKET"
    assert response.target.amount==0


def test_sma_baseline_is_distinct_from_price_atr_regime():
    bars=make_bars()
    baseline=decide(bars,func=sma_9_21_baseline_target_v1)
    trend=decide(bars)
    assert baseline.action=="SMA_SHORT"
    assert trend.action=="OPEN_SHORT"
    assert "no ATR/ER confirmation" in baseline.reason
    assert "ATR" in trend.reason


def test_lab_and_v3_catalogue_are_replay_only_and_tech100_2m():
    for catalog,runtime in (("pricetrend-1",STRATEGY_KEY_V3),
                            ("sma-9-21-baseline",BASELINE_KEY_V3)):
        assert strategy_v3(catalog).runtime_key==runtime
        assert strategy_v3(catalog).runtime_ready
        assert not strategy_adapter_v3(runtime).live_route_enabled
        assert catalog in PURE_V3
        assert sim_config_issues_v3(strategy_key=catalog,timeframe="2m",
                                    control_mode="Manuell",modifiers=())==()
        assert live_config_issues_v3(strategy_key=catalog,timeframe="2m",
                                     control_mode="Manuell",modifiers=())
        assert sim_config_issues_v3(strategy_key=catalog,timeframe="5m",
                                    control_mode="Manuell",modifiers=())
    source=Path("autotrader_v3_live_runtime_v1.py").read_text()
    assert "adapter.live_route_enabled" in source


def test_realistic_next_bar_paper_replay_charges_costs_and_isolates_no_orders():
    bars=make_bars(480)
    costs=ReplayCostsV2(point_value_nok=1.0,spread_bps=1.5,
                        variable_fee_bps=0.8,fixed_fee_nok=0.15,
                        starting_nav_nok=10000.0,lot_step=.01,max_lots=.01)
    trend=replay_v3_strategy_v2(strategy_key="pricetrend-1",
                               bars=bars,costs=costs,timeframe="2m")
    baseline=replay_v3_strategy_v2(strategy_key="sma-9-21-baseline",
                                  bars=bars,costs=costs,timeframe="2m")
    assert trend.trades>=1 and baseline.trades>=1
    assert trend.total_cost_nok>0 and baseline.total_cost_nok>0
    assert trend.events[0].at.minute%2==0
    assert all(event.at>=START+timedelta(minutes=150)
               for event in trend.events)
    with pytest.raises(ValueError,match="complete 2m"):
        replay_v3_strategy_v2(strategy_key="pricetrend-1",
                             bars=bars,costs=costs,timeframe="5m")
