from __future__ import annotations

"""Histogram Flip+Build V3 strategy.

Semantics:
- same-direction histogram slope: build one legal tranche per new closed bar
- opposite histogram slope while carrying exposure: flip the *target* directly
  to one tranche on the new side
- broker execution remains cross-flat: CLOSE -> confirm FLAT -> OPEN
"""

from autotrader_v3_macd_histogram_v1 import (
    MacdHistogramConfigV3,
    MacdHistogramDecisionV3,
)
from autotrader_v3_domain import TargetInventoryV3

STRATEGY_KEY_V3 = "macd-histogram-flip-build-v1"


def _q(value: float, tranche: float) -> float:
    quantized = round(float(value) / float(tranche)) * float(tranche)
    return 0.0 if abs(quantized) < float(tranche) / 2.0 else quantized


def macd_histogram_flip_build_target_v3(
    *,
    current_target: TargetInventoryV3,
    observation,
    previous_observation=None,
    config: MacdHistogramConfigV3 = MacdHistogramConfigV3(),
) -> MacdHistogramDecisionV3:
    """Flip immediately to +/- one tranche on slope reversal, then build.

    Strategy target may cross zero in one decision. The V3 execution planner is
    responsible for the hardened broker sequence CLOSE -> CONFIRM_FLAT -> OPEN.
    """

    h = float(observation.spread)
    current = _q(current_target.amount, config.tranche)

    if previous_observation is None:
        if h > 0:
            target = config.tranche
            reason = "initial positive histogram -> LONG one tranche"
        elif h < 0:
            target = -config.tranche
            reason = "initial negative histogram -> SHORT one tranche"
        else:
            target = current
            reason = "initial flat histogram -> HOLD"
    else:
        previous = float(previous_observation.spread)
        if h > previous:
            if current < 0:
                target = config.tranche
                reason = (
                    f"histogram slope flipped up {previous:+.6f}->{h:+.6f}; "
                    "SHORT target flips to LONG one tranche"
                )
            else:
                target = min(config.max_inventory, current + config.tranche)
                reason = (
                    f"histogram rising {previous:+.6f}->{h:+.6f}; "
                    "build LONG one tranche"
                )
        elif h < previous:
            if current > 0:
                target = -config.tranche
                reason = (
                    f"histogram slope flipped down {previous:+.6f}->{h:+.6f}; "
                    "LONG target flips to SHORT one tranche"
                )
            else:
                target = max(-config.max_inventory, current - config.tranche)
                reason = (
                    f"histogram falling {previous:+.6f}->{h:+.6f}; "
                    "build SHORT one tranche"
                )
        else:
            target = current
            reason = f"histogram unchanged {h:+.6f}; HOLD"

    target = _q(
        max(-config.max_inventory, min(config.max_inventory, target)),
        config.tranche,
    )

    if target == current:
        action = "HOLD"
    elif current != 0 and target != 0 and ((current > 0) != (target > 0)):
        action = "FLIP"
    elif current == 0:
        action = "OPEN"
    elif abs(target) > abs(current):
        action = "BUILD"
    else:
        action = "REDUCE"

    return MacdHistogramDecisionV3(
        target=TargetInventoryV3(target),
        action=action,
        reason=reason,
        histogram=h,
    )


__all__ = [
    "STRATEGY_KEY_V3",
    "macd_histogram_flip_build_target_v3",
]
