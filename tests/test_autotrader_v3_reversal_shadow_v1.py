from __future__ import annotations

import pytest

from autotrader_v3_aen2_sticky_regime_v1 import (
    StickyRegimeSnapshotV3,
    StickySignalSnapshotV3,
)
from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_reversal_shadow_v1 import (
    ReversalShadowConfigV3,
    evaluate_reversal_shadow_v3,
)


def _r(now=0.5, before=0.6, deadband=0.1):
    return StickyRegimeSnapshotV3(
        regime="BULL" if now > 0 else "BEAR",
        spread=now, previous_spread=before, deadband=deadband,
        weakening=False, timeframe_minutes=15,
    )


def _s(earlier=0.6, before=0.4, now=0.05):
    complete = all(value is not None for value in (earlier, before, now))
    return StickySignalSnapshotV3(
        spread=now, previous_spread=before, previous_previous_spread=earlier,
        favorable_bull=bool(complete and now > before),
        favorable_bear=bool(complete and now < before),
        persistent_adverse_bull=bool(complete and now < before < earlier),
        persistent_adverse_bear=bool(complete and now > before > earlier),
        timeframe_minutes=2,
    )


def _evaluate(position, base, regime=None, signal=None):
    return evaluate_reversal_shadow_v3(
        actual_inventory=TargetInventoryV3(position),
        base_target=TargetInventoryV3(base),
        regime=regime if regime is not None else _r(),
        signal=signal if signal is not None else _s(),
    )


def test_shadow_observer_never_enters_the_live_registry():
    from autotrader_v3_registry_v1 import LIVE_MODIFIERS_V3
    from autotrader_v3_strategy_registry_v1 import STRATEGIES_V3

    assert "reversal-shadow-v1" not in LIVE_MODIFIERS_V3
    assert "reversal-shadow-v1" not in STRATEGIES_V3


def test_flat_inventory_is_not_subject_to_defensive_shadow():
    decision = _evaluate(0.0, 0.01)
    assert decision.action == "NO_POSITION"
    assert decision.shadow_target.amount == 0.01


def test_one_adverse_signal_slope_does_not_undo_sticky_build():
    decision = _evaluate(0.02, 0.03, signal=_s(0.1, 0.4, 0.3))
    assert decision.action == "HOLD"
    assert decision.shadow_target.amount == 0.03


def test_persistent_countertrend_pauses_long_build_before_raw_cross():
    decision = _evaluate(0.02, 0.03, regime=_r(0.5, 0.6), signal=_s())
    assert decision.action == "PAUSE_BUILD"
    assert decision.shadow_target.amount == 0.02
    assert decision.base_target.amount == 0.03
    assert decision.persistent_countertrend


def test_persistent_countertrend_preserves_base_reduction():
    decision = _evaluate(0.04, 0.02, regime=_r(0.5, 0.6), signal=_s())
    assert decision.action == "WATCH"
    assert decision.shadow_target.amount == 0.02


def test_accelerating_countertrend_near_regime_zero_flattens_long_shadow_only():
    decision = _evaluate(0.04, 0.05, regime=_r(0.12, 0.22, 0.1), signal=_s())
    assert decision.action == "FLAT"
    assert decision.shadow_target.amount == 0
    assert decision.accelerating and decision.near_cross


def test_countertrend_far_from_regime_zero_does_not_prematurely_flatten():
    decision = _evaluate(0.02, 0.03, regime=_r(0.8, 0.9, 0.1), signal=_s())
    assert decision.action == "PAUSE_BUILD"
    assert decision.shadow_target.amount == 0.02


def test_mirrored_short_countertrend_can_pause_or_flatten():
    signal = _s(-0.6, -0.4, -0.05)
    paused = _evaluate(-0.02, -0.03, regime=_r(-0.5, -0.6), signal=signal)
    assert paused.action == "PAUSE_BUILD"
    assert paused.shadow_target.amount == -0.02
    flattened = _evaluate(-0.04, -0.05, regime=_r(-0.12, -0.22), signal=signal)
    assert flattened.action == "FLAT"
    assert flattened.shadow_target.amount == 0.0


@pytest.mark.parametrize(
    ("position", "raw_spread"),
    [(0.03, -0.001), (-0.03, 0.001)],
)
def test_raw_wrong_side_regime_keeps_fast_exit_reference(position, raw_spread):
    decision = _evaluate(position, position, regime=_r(raw_spread, 0.0), signal=_s())
    assert decision.action == "FLAT"
    assert decision.shadow_target.amount == 0.0


def test_missing_history_passes_through_without_inventing_signal():
    decision = _evaluate(
        0.02, 0.03,
        regime=_r(0.2, None),
        signal=_s(0.6, None, 0.1),
    )
    assert decision.action == "INSUFFICIENT_EVIDENCE"
    assert decision.shadow_target.amount == 0.03


def test_config_rejects_nonsensical_shadow_thresholds():
    with pytest.raises(ValueError):
        ReversalShadowConfigV3(acceleration_ratio=0.9)
    with pytest.raises(ValueError):
        ReversalShadowConfigV3(near_cross_deadband_multiple=0.0)
