from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import autotrader_v3_aen2_sticky_regime_v1 as strategy
from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_histogram_v1 import MacdHistogramConfigV3


CONFIG = MacdHistogramConfigV3(tranche=0.01, max_inventory=0.10)


def _obs(spread: float = 1.0, timeframe: int = 2):
    return SimpleNamespace(
        bar_time=datetime(2026, 10, 8, 14, 30, tzinfo=timezone.utc),
        closed_at=datetime(2026, 10, 8, 14, 32, tzinfo=timezone.utc),
        timeframe_minutes=timeframe,
        spread=spread,
    )


def _r(name: str, *, weakening: bool = False, spread: float = 4.0):
    return strategy.StickyRegimeSnapshotV3(
        regime=name,
        spread=spread,
        previous_spread=5.0 if weakening and name == strategy.REGIME_BULL else (
            -5.0 if weakening and name == strategy.REGIME_BEAR else spread
        ),
        deadband=0.5,
        weakening=weakening,
        timeframe_minutes=15,
    )


def _s(
    *,
    bull: bool = False,
    bear: bool = False,
    adverse_bull: bool = False,
    adverse_bear: bool = False,
):
    return strategy.StickySignalSnapshotV3(
        spread=1.0,
        previous_spread=0.5,
        previous_previous_spread=0.0,
        favorable_bull=bull,
        favorable_bear=bear,
        persistent_adverse_bull=adverse_bull,
        persistent_adverse_bear=adverse_bear,
        timeframe_minutes=2,
    )


def _patch(monkeypatch, regime, signal):
    monkeypatch.setattr(strategy, "classify_sticky_regime_v3", lambda **_: regime)
    monkeypatch.setattr(strategy, "classify_sticky_signal_v3", lambda **_: signal)


def test_bull_regime_builds_one_tranche_when_s_confirms(monkeypatch):
    _patch(monkeypatch, _r(strategy.REGIME_BULL), _s(bull=True))
    decision = strategy.aen2_sticky_regime_target_v3(
        current_target=TargetInventoryV3(0.02),
        observation=_obs(),
        config=CONFIG,
    )
    assert decision.target.amount == pytest.approx(0.03)
    assert decision.action == "BUILD"


def test_single_adverse_s_move_is_sticky_hold(monkeypatch):
    _patch(monkeypatch, _r(strategy.REGIME_BULL, weakening=True), _s())
    decision = strategy.aen2_sticky_regime_target_v3(
        current_target=TargetInventoryV3(0.04),
        observation=_obs(),
        config=CONFIG,
    )
    assert decision.target.amount == pytest.approx(0.04)
    assert decision.action == "HOLD"


def test_two_adverse_s_slopes_reduce_only_when_r_is_weakening(monkeypatch):
    _patch(
        monkeypatch,
        _r(strategy.REGIME_BULL, weakening=True),
        _s(adverse_bull=True),
    )
    decision = strategy.aen2_sticky_regime_target_v3(
        current_target=TargetInventoryV3(0.04),
        observation=_obs(),
        config=CONFIG,
    )
    assert decision.target.amount == pytest.approx(0.03)
    assert decision.action == "REDUCE"


def test_two_adverse_s_slopes_do_not_reduce_when_r_remains_strong(monkeypatch):
    _patch(
        monkeypatch,
        _r(strategy.REGIME_BULL, weakening=False),
        _s(adverse_bull=True),
    )
    decision = strategy.aen2_sticky_regime_target_v3(
        current_target=TargetInventoryV3(0.04),
        observation=_obs(),
        config=CONFIG,
    )
    assert decision.target.amount == pytest.approx(0.04)
    assert decision.action == "HOLD"


def test_confirmed_opposite_r_regime_forces_flat_before_reversal(monkeypatch):
    _patch(monkeypatch, _r(strategy.REGIME_BEAR, spread=-4.0), _s(bear=True))
    decision = strategy.aen2_sticky_regime_target_v3(
        current_target=TargetInventoryV3(0.05),
        observation=_obs(),
        config=CONFIG,
    )
    assert decision.target.amount == 0.0
    assert decision.action == "FLAT"


def test_neutral_deadband_preserves_existing_inventory_without_build(monkeypatch):
    _patch(monkeypatch, _r(strategy.REGIME_NEUTRAL, spread=0.1), _s(bull=True))
    decision = strategy.aen2_sticky_regime_target_v3(
        current_target=TargetInventoryV3(0.03),
        observation=_obs(),
        config=CONFIG,
    )
    assert decision.target.amount == pytest.approx(0.03)
    assert decision.action == "HOLD"


def test_bear_side_mirrors_build_and_sticky_reduce(monkeypatch):
    _patch(monkeypatch, _r(strategy.REGIME_BEAR, spread=-4.0), _s(bear=True))
    build = strategy.aen2_sticky_regime_target_v3(
        current_target=TargetInventoryV3(-0.02),
        observation=_obs(),
        config=CONFIG,
    )
    assert build.target.amount == pytest.approx(-0.03)

    _patch(
        monkeypatch,
        _r(strategy.REGIME_BEAR, weakening=True, spread=-4.0),
        _s(adverse_bear=True),
    )
    reduce = strategy.aen2_sticky_regime_target_v3(
        current_target=TargetInventoryV3(-0.04),
        observation=_obs(),
        config=CONFIG,
    )
    assert reduce.target.amount == pytest.approx(-0.03)
    assert reduce.action == "REDUCE"


def test_missing_history_fails_closed_to_hold():
    decision = strategy.aen2_sticky_regime_target_v3(
        current_target=TargetInventoryV3(0.02),
        observation=_obs(),
        source_bars=(),
        regime_timeframe_minutes=15,
        market_name="US Tech 100 NAS",
        config=CONFIG,
    )
    assert decision.target.amount == pytest.approx(0.02)
    assert decision.action == "HOLD"
