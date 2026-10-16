"""Regression tests for read-only V2 strategy reference and UI separation."""
from __future__ import annotations

from datetime import datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import autotrader_v2_flip_reference_lab_v1 as ref


START=datetime(2026,10,13,12,0,tzinfo=timezone.utc)


def bar(n,close=100.0,opening=None):
    stamp=START+timedelta(minutes=n)
    opening=close if opening is None else opening
    return SimpleNamespace(bar_time=stamp.isoformat(),market_name="Tech100",
                           open=opening,close=close,high=max(opening,close),
                           low=min(opening,close))


def test_v2_catalog_includes_five_closed_bar_macd_flip_variants():
    assert ref.SUPPORTED_V2_FLIP_MINUTES==(1,2,5,15,30)
    from autotrader_macd_timeframe_live_v1 import LIVE_MACD_CONTROL_STRATEGIES_V1
    assert set(LIVE_MACD_CONTROL_STRATEGIES_V1.values())=={1,2,5,15,30}


def test_v2_reference_uses_same_cross_helper_as_tradingdesk(monkeypatch):
    calls=[]
    def crosses(bars,*,timeframe_minutes):
        calls.append((len(bars),timeframe_minutes))
        return {START+timedelta(minutes=1):"LONG"}
    monkeypatch.setattr(ref,"_crosses_by_action_v1",crosses)
    x=ref.reference_v2_flip([bar(n) for n in range(4)],timeframe_minutes=2,
                            started_at=START,costs_enabled=False)
    assert calls==[(4,2)]
    assert len(x.decisions)==1
    assert x.decisions[0][1]=="LONG"
    assert x.executions==1


def test_v2_reference_no_lookahead_and_both_sides_cost(monkeypatch):
    monkeypatch.setattr(ref,"_crosses_by_action_v1",
        lambda bars,*,timeframe_minutes:{
            START+timedelta(minutes=1):"LONG",
            START+timedelta(minutes=2):"SHORT"})
    # Signal at 1min arrives after the first candle, not before.
    xs=[bar(0,110,100),bar(1,110),bar(2,110),bar(3,110)]
    paid=ref.reference_v2_flip(xs,timeframe_minutes=2,
                                started_at=START,commission_side_bps=8,
                                quoted_spread_bps=2)
    free=ref.reference_v2_flip(xs,timeframe_minutes=2,
                                started_at=START,costs_enabled=False,
                                commission_side_bps=8,quoted_spread_bps=2)
    assert paid.gross_pct==pytest.approx(0)
    assert free.gross_pct==pytest.approx(0)
    assert free.return_pct==pytest.approx(0)
    assert paid.executions==2
    assert paid.estimated_broker_orders==3
    assert paid.return_pct < -0.26
    assert 0.26 < paid.total_cost_pct < 0.28


def test_v2_reference_has_historical_zero_start_before_first_cross(monkeypatch):
    monkeypatch.setattr(ref,"_crosses_by_action_v1",
        lambda bars,*,timeframe_minutes:{
            START+timedelta(minutes=1):"LONG",
            START+timedelta(minutes=4):"SHORT"})
    xs=[bar(n) for n in range(6)]
    # A warmup cross before the analysis start must not be counted.
    result=ref.reference_v2_flip(xs,timeframe_minutes=2,
                                 started_at=START+timedelta(minutes=2))
    assert len(result.decisions)==1
    assert result.decisions[0][1]=="SHORT"
    assert result.executions==1


def test_new_dropdown_preserves_legacy_and_nextgen_path():
    page=Path("pages/0_Live_Sim_Lab.py").read_text(encoding="utf-8")
    ui=Path("autotrader_v2_strategy_lab_ui_v1.py").read_text(encoding="utf-8")
    assert '("AEn Core · Adaptive Engine","Nye strategier · MACD","Inversjonstest · MACD","Unngå tap V1 · NAV-SIM","V2 strategies","Legacy strategies")' in page
    assert 'if universe=="V2 strategies"' in page
    assert 'render_v2_strategy_lab_v1()' in page
    assert 'render_nextgen_macd_lab_v1()' in page
    assert "v2_strategy_catalog_v1" in ui
    assert "reference_v2_flip" in ui
    assert "Saxo-ordrer" in ui
    assert "set_live_enabled_v2" not in ui
    assert "place_order" not in ui
    assert "migrate_legacy_strategy_v3" not in ui


def test_v2_strategy_catalog_excludes_v3_runtime_keys():
    from autotrader_v2_strategy_lab_ui_v1 import v2_strategy_catalog_v1
    keys={x.key for x in v2_strategy_catalog_v1()}
    assert "macd-2m-flip-control-shadow-v1" in keys
    assert "macd-5m-flip-control-shadow-v1" in keys
    assert "macd-trailing-v1" not in keys


def test_v2_reference_rejects_unsupported_signal_period():
    with pytest.raises(ValueError,match="not present"):
        ref.reference_v2_flip([bar(0)],timeframe_minutes=10,started_at=START)
