"""Broader mechanical strategy coverage and cost-mode isolation in Strategy Lab v2."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
from math import sin
from types import SimpleNamespace

import pytest

from strategy_lab_v2_replay import (
    PURE_V3,ReplayCostsV2,replay_v3_strategy_v2,strategy_catalog_v2,
)

START=datetime(2026,10,18,0,0,tzinfo=timezone.utc)
COSTS=ReplayCostsV2(point_value_nok=10.,spread_bps=8.,
                    variable_fee_bps=0.,fixed_fee_nok=0.,
                    lot_step=.01,max_lots=.03,starting_nav_nok=10000.)


def synthetic_saxo_bars(length=720):
    result=[]
    for i in range(length):
        price=30000+i*.15+45*sin(i/29)
        op=price-1
        result.append(SimpleNamespace(
            bar_time=(START+timedelta(minutes=i)).isoformat(),
            open=op,high=price+2,low=op-2,close=price,
            market_name="US Tech100",volume=250.,quality_flags=1,
        ))
    return tuple(result)


def test_all_supported_pure_v3_methods_appear_in_catalog():
    names={x["key"] for family in strategy_catalog_v2().values() for x in family}
    assert set(PURE_V3).issubset(names)
    assert len(PURE_V3)>=18
    for key in (
        "macd-stoch-v1","macd-regime-histogram",
        "vwap-regime-histogram","aen2-sticky-regime",
        "aen21-sticky-fast-exit","rhythm-trend-1",
        "rhythm-build-fractal","rhythm-trend-fractal",
    ):
        assert key in PURE_V3


@pytest.mark.parametrize("strategy",(
    "macd-stoch-v1",
    "vwap-regime-histogram",
    "macd-regime-histogram",
    "aen2-sticky-regime",
    "aen21-sticky-fast-exit",
    "rhythm-trend-1",
    "rhythm-build-fractal",
    "rhythm-trend-fractal",
))
def test_extended_pure_replay_never_exceeds_limit(strategy):
    bars=synthetic_saxo_bars()
    timeframe="1m" if "rhythm" in strategy else "2m"
    result=replay_v3_strategy_v2(
        strategy_key=strategy,bars=bars,costs=COSTS,timeframe=timeframe)
    assert len(result.points)==720
    assert result.cost_source=="MANUAL_SCENARIO"
    assert all(abs(p.lots)<=.0300001 for p in result.points)
    assert all(e.at>=START for e in result.events)
    assert not any(e.kind=="GAP_FLAT" for e in result.events)


def test_exact_manual_branch_not_substring_saxo_verification():
    page=Path("pages/0_Strategy_Lab_V2.py").read_text()
    assert 'saxo_mode=(cost_mode==SAXO_COST_OPTION)' in page
    assert 'if "Saxo" in cost_mode:' not in page
    assert page.count("if saxo_mode:")>=2
    assert 'Manuelt scenario (ikke Saxo-verifisert)' in page
    assert "Saxo-kalibrert SIM mangler verifisering av:" in page
    assert "rhythm-trend-fractal" in page
