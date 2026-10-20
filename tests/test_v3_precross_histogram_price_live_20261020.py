"""Mechanical V3 MACD divergence + completed 1m price confirmation."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_histogram_v1 import MacdHistogramConfigV3
import autotrader_v3_precross_price_v1 as p
from autotrader_v3_registry_v1 import live_config_issues_v3,strategy_v3
from autotrader_v3_strategy_registry_v1 import strategy_adapter_v3
from autotrader_v3_strategy_sizing_v1 import strategy_amount_config_v3
from autotrader_v3_instance_controls_ui_v1 import _rhythm_selection_defaults_v3

CLOCK=datetime(2026,10,20,14,20,tzinfo=timezone.utc)
CFG=MacdHistogramConfigV3(tranche=.01,max_inventory=.10)


def bars(direction=1,*,gap=False):
    """Five closed 1m candles with a real final breakout in desired direction."""
    closes=[100.,100.1,100.2,100.3,101.25] if direction==1 else [
        100.,99.9,99.8,99.7,98.75]
    a=[]
    for i,close in enumerate(closes):
        op=(close-.65 if i==4 and direction==1 else
            close+.65 if i==4 and direction==-1 else close-.05)
        high=max(op,close)+.1
        low=min(op,close)-.1
        time=CLOCK-timedelta(minutes=5-i)
        if gap and i==3:
            time-=timedelta(minutes=1)
        a.append(SimpleNamespace(
            bar_time=time,open=op,high=high,low=low,close=close))
    return tuple(a)


def source():
    # A 2m complete-bar proof that respects the same decision cutoff.
    return tuple(SimpleNamespace(
        bar_time=CLOCK-timedelta(minutes=100-i),
        open=100.,high=101.,low=99.,close=100.,
        point=((CLOCK-timedelta(minutes=100-i)).isoformat(),100.))
        for i in range(100))


def observation():
    return SimpleNamespace(
        bar_time=CLOCK-timedelta(minutes=1),closed_at=CLOCK,
        spread=.03)


def setup_hist(monkeypatch,*,prev=.4,current=.2):
    hh=[.30+i*.002 for i in range(8)]+[prev,current]
    monkeypatch.setattr(p,"_observations_v3",lambda **kw:tuple(
        SimpleNamespace(spread=val,closed_at=CLOCK-timedelta(minutes=2*(9-i)))
        for i,val in enumerate(hh)))


@pytest.mark.parametrize("strategy,side",[
    (p.precross_price_target_v3,-1),
    (p.precross_price_target_v3,1),
    (p.histogram_price_target_v3,-1),
    (p.histogram_price_target_v3,1),
])
def test_signal_uses_histogram_slope_and_actual_closed_price(monkeypatch,strategy,side):
    setup_hist(monkeypatch,prev=.5,current=.3) if side==-1 else setup_hist(
        monkeypatch,prev=-.5,current=-.3)
    result=strategy(current_target=TargetInventoryV3(0),observation=observation(),
                    bars=bars(side),source_bars=source(),market_name="Tech100",
                    config=CFG)
    assert result.target.amount==side*.01
    assert result.action=="OPEN"
    if strategy is p.precross_price_target_v3:
        # Histogram LEVEL still says the opposite sign => genuine pre-cross.
        assert "BEFORE 2m MACD zero-cross" in result.reason


@pytest.mark.parametrize("strategy",[
    p.precross_price_target_v3,p.histogram_price_target_v3,
])
def test_adverse_histogram_slope_exits_first_without_opposite_side(monkeypatch,strategy):
    setup_hist(monkeypatch,prev=.45,current=.25)
    result=strategy(current_target=TargetInventoryV3(.01),
                    observation=observation(),bars=bars(-1),source_bars=source(),
                    market_name="Tech100",config=CFG)
    assert result.target.amount==0
    assert result.action=="FLAT_CONTRACTION"


def test_parallel_macd_prevents_new_exposure(monkeypatch):
    setup_hist(monkeypatch,prev=.4,current=.4)
    r=p.histogram_price_target_v3(
        current_target=TargetInventoryV3(0),observation=observation(),
        bars=bars(1),source_bars=source(),market_name="Tech100",config=CFG)
    assert r.target.amount==0 and r.action=="FLAT_PARALLEL"


def test_missing_one_minute_or_future_price_fail_closed(monkeypatch):
    setup_hist(monkeypatch,prev=.45,current=.25)
    for incomplete in (bars(-1,gap=True),bars(-1)[:-1],
                       bars(-1)+ (SimpleNamespace(
                           bar_time=CLOCK+timedelta(minutes=1),
                           open=102,high=103,low=101,close=102),)):
        r=p.precross_price_target_v3(
            current_target=TargetInventoryV3(.01),observation=observation(),
            bars=incomplete,source_bars=source(),market_name="Tech100",config=CFG)
        assert r.target.amount==0


def test_live_registry_is_real_and_requires_1m_signal_for_2m_macd():
    for catalog in ("precross-price-1m-macd2m","histogram-price-1m-macd2m"):
        spec=strategy_v3(catalog)
        assert spec.runtime_ready and spec.runtime_key
        adapter=strategy_adapter_v3(spec.runtime_key)
        assert adapter.live_route_enabled
        assert live_config_issues_v3(
            strategy_key=catalog,timeframe="1m",
            control_mode="Manuell",modifiers=())==()
        assert any("krever 1m" in issue for issue in live_config_issues_v3(
            strategy_key=catalog,timeframe="2m",
            control_mode="Manuell",modifiers=()))
        assert _rhythm_selection_defaults_v3("macd-flip",catalog)["timeframe"]=="1m"


def test_common_v3_broker_sizing_and_causal_driver():
    code=Path("autotrader_v3_closed_bar_driver_v1.py").read_text()
    size=Path("autotrader_v3_strategy_sizing_v1.py").read_text()
    assert "precross_price_target_v3" in code
    assert "histogram_price_target_v3" in code
    assert 'extra["source_bars"] = source_bars' in code
    assert "PRECROSS_KEY_V3,HIST_PRICE_KEY_V3" in size
    signal=Path("autotrader_v3_precross_price_v1.py").read_text()
    for forbidden in ("place_order(", "_post(", "set_live_enabled_v3(",
                      "SaxoOrderRequest", "open_pnl_exact("):
        assert forbidden not in signal
