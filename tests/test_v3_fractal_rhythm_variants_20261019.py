"""Causal Fraktal#1 tempo overlays, SIM-only routing and baseline invariants."""
from __future__ import annotations

from datetime import datetime,timedelta,timezone
from math import sin,pi
from pathlib import Path
from types import SimpleNamespace

import pytest

from autotrader_macd_dry_run_v2 import MacdObservationV2
from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_stoch_v2 import MacdStochV2DecisionV3
from autotrader_v3_macd_histogram_v1 import MacdHistogramConfigV3,MacdHistogramDecisionV3
from autotrader_v3_macd_trailing_v1 import MacdTrailingConfigV3
from autotrader_v3_registry_v1 import (
    live_config_issues_v3,sim_config_issues_v3,strategy_v3,
)
from autotrader_v3_fractal_cadence_v1 import (
    FractalCadenceV1,fractal_cadence_v1,cadence_interval_minutes_v1,
)
import autotrader_v3_fractal_rhythm_variants_v1 as f
from autotrader_v3_strategy_registry_v1 import STRATEGIES_V3,evaluate_strategy_bar_v3

START=datetime(2026,10,19,12,0,tzinfo=timezone.utc)


def stream(n=240,period=6,*,gap=None,future=False):
    bars=[]
    for i in range(n):
        if i==gap:
            continue
        p=100+0.6*sin(2*pi*i/period)
        bars.append(SimpleNamespace(
            bar_time=START+timedelta(minutes=i),
            open=p,high=p+0.1,low=p-0.1,close=p))
    return tuple(bars)


def obs(start=START):
    return MacdObservationV2(bar_time=start,macd=2,signal=0)


def snapshot(level,reason="test"):
    return FractalCadenceV1(level,3.0,(1,1,1),START,reason)


def test_fractal_scale_source_and_no_hindsight():
    from autotrader_v3_fraktal1_v1 import REVERSION_THRESHOLDS_PCT
    assert REVERSION_THRESHOLDS_PCT==(0.05,0.15,0.35)
    candles=stream()
    cut=START+timedelta(minutes=240)
    original=fractal_cadence_v1(candles,closed_at=cut)
    assert original.level in {"FAST","NORMAL","SLOW"}
    assert original.median_micro_confirm_minutes is not None
    assert original.last_confirmation <= cut
    # Future bars cannot leak into the same decision or retrospectively
    # change speed just because a future swing confirms the old pivot.
    later=tuple(SimpleNamespace(
        bar_time=cut+timedelta(minutes=i),
        open=105+i,high=105.1+i,low=104.9+i,close=105+i)
        for i in range(20))
    assert fractal_cadence_v1(candles+later,closed_at=cut)==original
    assert "confirmed" in original.reason


def test_missed_minute_or_misaligned_candle_fails_unknown():
    clock=START+timedelta(minutes=240)
    assert fractal_cadence_v1(stream(gap=235),closed_at=clock).level=="UNKNOWN"
    assert fractal_cadence_v1(stream(3),closed_at=clock).level=="UNKNOWN"
    assert fractal_cadence_v1(stream(),closed_at=clock+timedelta(seconds=1)).level=="UNKNOWN"


def test_speed_slots_are_never_more_aggressive_than_base():
    assert [cadence_interval_minutes_v1(s,strategy="build")
            for s in ("FAST","NORMAL","SLOW","UNKNOWN")]==[1,2,4,None]
    assert [cadence_interval_minutes_v1(s,strategy="trend")
            for s in ("FAST","NORMAL","SLOW","UNKNOWN")]==[5,10,15,None]
    with pytest.raises(ValueError):
        cadence_interval_minutes_v1("FAST",strategy="not-strategy")


def test_sim_only_route_and_catalog_validation():
    for catalog,runtime in [
        ("rhythm-build-fractal",f.RHYTHM_BUILD_FRACTAL_KEY_V3),
        ("rhythm-trend-fractal",f.RHYTHM_TREND_FRACTAL_KEY_V3),
    ]:
        spec=strategy_v3(catalog)
        assert spec.runtime_key==runtime and spec.runtime_ready
        assert runtime in STRATEGIES_V3
        assert not STRATEGIES_V3[runtime].live_route_enabled
        assert sim_config_issues_v3(
            strategy_key=catalog,timeframe="1m",control_mode="Manuell",
            modifiers=(),regime_timeframe="15m")==()
        assert any("SIM" in x or "LIVE er sperret" in x
                   for x in live_config_issues_v3(
                       strategy_key=catalog,timeframe="1m",control_mode="Manuell",
                       modifiers=(),regime_timeframe="15m"))
        assert any("1m" in x for x in sim_config_issues_v3(
            strategy_key=catalog,timeframe="5m",control_mode="Manuell",
            modifiers=(),regime_timeframe="15m"))
    assert any("15m" in x for x in sim_config_issues_v3(
        strategy_key="rhythm-trend-fractal",timeframe="1m",
        control_mode="Manuell",modifiers=(),regime_timeframe="30m"))


@pytest.fixture
def baseline(monkeypatch):
    state={"build":.02,"trend":.02,"action":"BUILD"}
    def fake_build(**kwargs):
        return MacdStochV2DecisionV3(
            TargetInventoryV3(state["build"]),state["action"],
            "baseline build",2.0)
    def fake_trend(**kwargs):
        return MacdHistogramDecisionV3(
            TargetInventoryV3(state["trend"]),state["action"],
            "baseline trend",2.0)
    monkeypatch.setattr(f,"macd_stoch_rhythm_build_target_v3",fake_build)
    monkeypatch.setattr(f,"rhythm_trend_target_v3",fake_trend)
    return state


@pytest.mark.parametrize("level,minute,expected",[
    ("FAST",1,.02),("NORMAL",1,.01),("NORMAL",2,.02),
    ("SLOW",2,.01),("SLOW",4,.02),("UNKNOWN",4,.01),
])
def test_build_fractal_throttles_adds_not_parent_signal(
    monkeypatch,baseline,level,minute,expected,
):
    monkeypatch.setattr(f,"fractal_cadence_v1",lambda *a,**kw:snapshot(level))
    decision=f.rhythm_build_fractal_target_v3(
        current_target=TargetInventoryV3(.01),
        observation=obs(START+timedelta(minutes=minute-1)),
        bars=(),source_bars=(),
        config=MacdTrailingConfigV3())
    assert decision.target.amount==pytest.approx(expected)
    assert decision.spread==2.0
    assert "Fraktal tempo:" in decision.reason


@pytest.mark.parametrize("level,minute,expected",[
    ("FAST",5,.02),("NORMAL",5,.01),("NORMAL",10,.02),
    ("SLOW",10,.01),("SLOW",15,.02),("UNKNOWN",15,.01),
])
def test_trend_fractal_throttles_5m_adds(
    monkeypatch,baseline,level,minute,expected,
):
    monkeypatch.setattr(f,"fractal_cadence_v1",lambda *a,**kw:snapshot(level))
    decision=f.rhythm_trend_fractal_target_v3(
        current_target=TargetInventoryV3(.01),
        observation=obs(START+timedelta(minutes=minute-1)),
        source_bars=(),bars=(),
        config=MacdHistogramConfigV3())
    assert decision.target.amount==pytest.approx(expected)


@pytest.mark.parametrize("mode",["build","trend"])
def test_no_tempo_filter_can_delay_flat_or_trim(monkeypatch,baseline,mode):
    monkeypatch.setattr(f,"fractal_cadence_v1",
                        lambda *a,**kw:snapshot("UNKNOWN"))
    decision=(f.rhythm_build_fractal_target_v3 if mode=="build"
              else f.rhythm_trend_fractal_target_v3)
    cfg=MacdTrailingConfigV3() if mode=="build" else MacdHistogramConfigV3()
    baseline[mode]=0
    baseline["action"]="OPPOSITE_FLAT"
    close=decision(current_target=TargetInventoryV3(.04),
                   observation=obs(),source_bars=(),bars=(),config=cfg)
    assert close.target.amount==0.0
    assert close.action=="OPPOSITE_FLAT"
    baseline[mode]=.01
    baseline["action"]="TRIM_CHOP"
    trim=decision(current_target=TargetInventoryV3(.04),
                  observation=obs(),source_bars=(),bars=(),config=cfg)
    assert trim.target.amount==.01
    assert trim.action=="TRIM_CHOP"


def test_real_v3_cursor_prevents_second_add_on_same_candle(monkeypatch,baseline,tmp_path):
    monkeypatch.setattr(f,"fractal_cadence_v1",lambda *a,**kw:snapshot("FAST"))
    path=str(tmp_path/"fractal-adapt.db")
    for key,config in [
        (f.RHYTHM_BUILD_FRACTAL_KEY_V3,MacdTrailingConfigV3()),
        (f.RHYTHM_TREND_FRACTAL_KEY_V3,MacdHistogramConfigV3()),
    ]:
        name="sim:"+key
        kw=dict(strategy_key=key,trader_id=name,db_path=path,
                observation=obs(START),bars=(),source_bars=(),config=config,
                regime_timeframe_minutes=15,market_name="US Tech 100")
        first=evaluate_strategy_bar_v3(**kw)
        assert first.is_new and first.decision.target.amount==pytest.approx(.02)
        again=evaluate_strategy_bar_v3(**kw)
        assert not again.is_new
        assert again.decision.target.amount==pytest.approx(.02)


def test_no_saxo_order_or_live_authority_added():
    for path in [
        "autotrader_v3_fractal_cadence_v1.py",
        "autotrader_v3_fractal_rhythm_variants_v1.py",
    ]:
        src=Path(path).read_text()
        for forbidden in ("place_order(","reserve_order_v3","set_live_enabled",
                          "SaxoOrderRequest","from database import"):
            assert forbidden not in src
