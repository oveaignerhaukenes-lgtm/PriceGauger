from __future__ import annotations

"""Pure, research-only pre-cross reversal observer for V3 sticky strategies.

This module is deliberately NOT registered as a LIVE/SIM modifier and is not
imported by the execution path. It proposes counterfactual targets so that a
future replay can measure whether defensive action improves on Aen#2/#2.1.
It does not persist state, read brokers or emit orders.
"""

from dataclasses import dataclass
from math import isfinite

from autotrader_v3_aen2_sticky_regime_v1 import (
    StickyRegimeSnapshotV3,
    StickySignalSnapshotV3,
)
from autotrader_v3_domain import TargetInventoryV3


@dataclass(frozen=True, slots=True)
class ReversalShadowConfigV3:
    """Conservative, explicitly provisional shadow-only thresholds."""

    acceleration_ratio: float = 1.5
    near_cross_deadband_multiple: float = 1.5

    def __post_init__(self) -> None:
        if not isfinite(self.acceleration_ratio) or self.acceleration_ratio < 1.0:
            raise ValueError("acceleration_ratio must be finite and >= 1")
        if not isfinite(self.near_cross_deadband_multiple) or self.near_cross_deadband_multiple <= 0:
            raise ValueError("near_cross_deadband_multiple must be positive and finite")


@dataclass(frozen=True, slots=True)
class ReversalShadowDecisionV3:
    action: str
    base_target: TargetInventoryV3
    shadow_target: TargetInventoryV3
    reason: str
    persistent_countertrend: bool = False
    accelerating: bool = False
    near_cross: bool = False


def _finite(value: float | None) -> bool:
    return value is not None and isfinite(float(value))


def _pause_expansion(
    actual: TargetInventoryV3, base: TargetInventoryV3
) -> TargetInventoryV3:
    """Freeze same-side growth, never cancel a base strategy's reduction/exit."""
    if actual.amount > 0 and base.amount > actual.amount:
        return actual
    if actual.amount < 0 and base.amount < actual.amount:
        return actual
    return base


def evaluate_reversal_shadow_v3(
    *,
    actual_inventory: TargetInventoryV3,
    base_target: TargetInventoryV3,
    regime: StickyRegimeSnapshotV3,
    signal: StickySignalSnapshotV3,
    config: ReversalShadowConfigV3 = ReversalShadowConfigV3(),
) -> ReversalShadowDecisionV3:
    """Propose HOLD / PAUSE_BUILD / FLAT without altering execution authority.

    An existing position may be defended. This observer never proposes opening
    or pyramiding an opposite position; any opposite-side entry remains solely
    a base-strategy decision. Missing evidence leaves the base target intact.
    """
    position = actual_inventory.amount
    if position == 0.0:
        return ReversalShadowDecisionV3(
            "NO_POSITION", base_target, base_target,
            "Flat broker inventory: no existing side to defend",
        )

    raw_r = regime.spread
    if not _finite(raw_r):
        return ReversalShadowDecisionV3(
            "INSUFFICIENT_EVIDENCE", base_target, base_target,
            "Raw regime spread unavailable; no shadow intervention",
        )

    # Aen#2.1 already contains this exit. Keep it in the observer as a
    # reference state, never as a claim of additional predictive advantage.
    if (position > 0 and raw_r < 0) or (position < 0 and raw_r > 0):
        return ReversalShadowDecisionV3(
            "FLAT", base_target, TargetInventoryV3(0.0),
            "Raw R spread already crossed against held inventory",
        )

    r_previous = regime.previous_spread
    s_now, s_prev, s_prevprev = (
        signal.spread, signal.previous_spread, signal.previous_previous_spread
    )
    if not all(_finite(value) for value in (r_previous, s_now, s_prev, s_prevprev)):
        return ReversalShadowDecisionV3(
            "INSUFFICIENT_EVIDENCE", base_target, base_target,
            "R/S slope history incomplete; no shadow intervention",
        )

    is_long = position > 0
    r_weakening = raw_r < r_previous if is_long else raw_r > r_previous
    adverse = (
        s_now < s_prev < s_prevprev
        if is_long else s_now > s_prev > s_prevprev
    )
    if not (r_weakening and adverse):
        return ReversalShadowDecisionV3(
            "HOLD", base_target, base_target,
            "No persistent adverse S slopes together with weakening R",
        )

    first_move = abs(s_prev - s_prevprev)
    last_move = abs(s_now - s_prev)
    accelerating = first_move > 0 and last_move >= first_move * config.acceleration_ratio
    near_cross = (
        _finite(regime.deadband)
        and regime.deadband > 0
        and abs(raw_r) <= regime.deadband * config.near_cross_deadband_multiple
    )

    if accelerating and near_cross:
        return ReversalShadowDecisionV3(
            "FLAT", base_target, TargetInventoryV3(0.0),
            "Two adverse S slopes accelerate while weakening R approaches zero",
            persistent_countertrend=True, accelerating=True, near_cross=True,
        )

    paused = _pause_expansion(actual_inventory, base_target)
    if paused != base_target:
        return ReversalShadowDecisionV3(
            "PAUSE_BUILD", base_target, paused,
            "Persistent adverse S slopes plus weakening R: shadow caps same-side build",
            persistent_countertrend=True,
            accelerating=accelerating, near_cross=near_cross,
        )

    return ReversalShadowDecisionV3(
        "WATCH", base_target, base_target,
        "Countertrend observed; existing base reduction/hold is preserved",
        persistent_countertrend=True,
        accelerating=accelerating, near_cross=near_cross,
    )


__all__ = [
    "ReversalShadowConfigV3",
    "ReversalShadowDecisionV3",
    "evaluate_reversal_shadow_v3",
]
