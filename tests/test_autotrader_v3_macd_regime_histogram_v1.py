from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import autotrader_v3_macd_regime_histogram_v1 as strategy
from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_histogram_v1 import MacdHistogramConfigV3


START=datetime(2026,10,7,0,0,tzinfo=timezone.utc)
CONFIG=MacdHistogramConfigV3(tranche=0.01,max_inventory=0.10)


def _obs(spread:float, *, minute:int=700):
    at=START+timedelta(minutes=minute)
    return SimpleNamespace(
        bar_time=at-timedelta(minutes=5),
        closed_at=at,
        spread=spread,
    )


def _regime(name:str, spread:float):
    return strategy.MacdRegimeV3(name,spread,15)


def test_bull_regime_forbids_short_even_when_fast_histogram_falls(monkeypatch):
    monkeypatch.setattr(strategy,"classify_macd_regime_v3",lambda **_:_regime(strategy.REGIME_BULL,0.4))
    from_short=strategy.macd_regime_histogram_target_v3(
        current_target=TargetInventoryV3(-0.03),
        observation=_obs(-1.2),
        previous_observation=_obs(-0.8,minute=695),
        config=CONFIG,
    )
    from_flat=strategy.macd_regime_histogram_target_v3(
        current_target=TargetInventoryV3(0.0),
        observation=_obs(-1.2),
        previous_observation=_obs(-0.8,minute=695),
        config=CONFIG,
    )
    assert from_short.target.amount == 0.0
    assert from_flat.target.amount == 0.0


def test_bull_regime_uses_signal_histogram_only_to_build_or_reduce_long(monkeypatch):
    monkeypatch.setattr(strategy,"classify_macd_regime_v3",lambda **_:_regime(strategy.REGIME_BULL,0.4))
    build=strategy.macd_regime_histogram_target_v3(
        current_target=TargetInventoryV3(0.02),
        observation=_obs(1.2),
        previous_observation=_obs(0.8,minute=695),
        config=CONFIG,
    )
    reduce=strategy.macd_regime_histogram_target_v3(
        current_target=TargetInventoryV3(0.02),
        observation=_obs(0.4),
        previous_observation=_obs(0.8,minute=695),
        config=CONFIG,
    )
    assert build.target.amount == pytest.approx(0.03)
    assert build.action == "BUILD"
    assert reduce.target.amount == pytest.approx(0.01)
    assert reduce.action == "REDUCE"


def test_bear_regime_mirrors_bull_policy(monkeypatch):
    monkeypatch.setattr(strategy,"classify_macd_regime_v3",lambda **_:_regime(strategy.REGIME_BEAR,-0.4))
    build=strategy.macd_regime_histogram_target_v3(
        current_target=TargetInventoryV3(-0.02),
        observation=_obs(-1.2),
        previous_observation=_obs(-0.8,minute=695),
        config=CONFIG,
    )
    forbidden=strategy.macd_regime_histogram_target_v3(
        current_target=TargetInventoryV3(0.02),
        observation=_obs(1.2),
        previous_observation=_obs(0.8,minute=695),
        config=CONFIG,
    )
    assert build.target.amount == pytest.approx(-0.03)
    assert forbidden.target.amount == 0.0


def test_missing_regime_data_holds_instead_of_guessing():
    decision=strategy.macd_regime_histogram_target_v3(
        current_target=TargetInventoryV3(0.02),
        observation=_obs(1.2),
        previous_observation=_obs(0.8,minute=695),
        source_bars=(),
        regime_timeframe_minutes=15,
        market_name="US Tech 100 NAS",
        config=CONFIG,
    )
    assert decision.target.amount == pytest.approx(0.02)
    assert decision.action == "HOLD"


def _source_bars(direction:float):
    rows=[]
    price=100.0
    for index in range(700):
        if index >= 500:
            elapsed=index-500
            price += direction*(0.02 + elapsed*0.0008)
        rows.append(SimpleNamespace(
            bar_time=(START+timedelta(minutes=index)).isoformat(),
            point=((START+timedelta(minutes=index)).isoformat(),price),
        ))
    return tuple(rows)


@pytest.mark.parametrize(
    ("direction","expected"),
    [(1.0,strategy.REGIME_BULL),(-1.0,strategy.REGIME_BEAR)],
)
def test_regime_is_derived_from_configured_closed_macd_timeframe(direction,expected):
    result=strategy.classify_macd_regime_v3(
        source_bars=_source_bars(direction),
        closed_at=START+timedelta(minutes=700),
        regime_timeframe_minutes=15,
        market_name="US Tech 100 NAS",
    )
    assert result.regime == expected
    assert result.timeframe_minutes == 15
