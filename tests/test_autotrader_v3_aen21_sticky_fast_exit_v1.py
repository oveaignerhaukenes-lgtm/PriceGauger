from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import autotrader_v3_aen21_sticky_fast_exit_v1 as strategy
from autotrader_v3_aen2_sticky_regime_v1 import (
    REGIME_NEUTRAL,
    StickyRegimeSnapshotV3,
)
from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_histogram_v1 import (
    MacdHistogramConfigV3,
    MacdHistogramDecisionV3,
)


CONFIG = MacdHistogramConfigV3(tranche=0.01, max_inventory=0.10)


def _obs():
    return SimpleNamespace(
        bar_time=datetime(2026, 10, 8, 20, 0, tzinfo=timezone.utc),
        closed_at=datetime(2026, 10, 8, 20, 2, tzinfo=timezone.utc),
        timeframe_minutes=2,
        spread=1.0,
    )


def _neutral(spread: float):
    return StickyRegimeSnapshotV3(
        regime=REGIME_NEUTRAL,
        spread=spread,
        previous_spread=-0.1 if spread > 0 else 0.1,
        deadband=0.5,
        weakening=False,
        timeframe_minutes=15,
    )


def test_raw_positive_r_exits_short_inside_deadband(monkeypatch):
    monkeypatch.setattr(strategy, "classify_sticky_regime_v3", lambda **_: _neutral(0.1))
    decision = strategy.aen21_sticky_fast_exit_target_v3(
        current_target=TargetInventoryV3(-0.09),
        observation=_obs(),
        config=CONFIG,
    )
    assert decision.target.amount == 0.0
    assert decision.action == "FLAT"
    assert "FAST EXIT" in decision.reason


def test_raw_negative_r_exits_long_inside_deadband(monkeypatch):
    monkeypatch.setattr(strategy, "classify_sticky_regime_v3", lambda **_: _neutral(-0.1))
    decision = strategy.aen21_sticky_fast_exit_target_v3(
        current_target=TargetInventoryV3(0.07),
        observation=_obs(),
        config=CONFIG,
    )
    assert decision.target.amount == 0.0
    assert decision.action == "FLAT"


def test_raw_cross_does_not_open_new_side_before_deadband_confirmation(monkeypatch):
    monkeypatch.setattr(strategy, "classify_sticky_regime_v3", lambda **_: _neutral(0.1))
    delegated = MacdHistogramDecisionV3(
        target=TargetInventoryV3(0.0),
        action="HOLD",
        reason="R inside deadband -> sticky HOLD",
        histogram=1.0,
    )
    monkeypatch.setattr(strategy, "aen2_sticky_regime_target_v3", lambda **_: delegated)
    decision = strategy.aen21_sticky_fast_exit_target_v3(
        current_target=TargetInventoryV3(0.0),
        observation=_obs(),
        config=CONFIG,
    )
    assert decision.target.amount == 0.0
    assert decision.action == "HOLD"


def test_same_side_inventory_keeps_original_sticky_policy(monkeypatch):
    monkeypatch.setattr(strategy, "classify_sticky_regime_v3", lambda **_: _neutral(0.1))
    delegated = MacdHistogramDecisionV3(
        target=TargetInventoryV3(0.04),
        action="HOLD",
        reason="sticky hold",
        histogram=1.0,
    )
    monkeypatch.setattr(strategy, "aen2_sticky_regime_target_v3", lambda **_: delegated)
    decision = strategy.aen21_sticky_fast_exit_target_v3(
        current_target=TargetInventoryV3(0.04),
        observation=_obs(),
        config=CONFIG,
    )
    assert decision.target.amount == pytest.approx(0.04)
    assert decision.action == "HOLD"
