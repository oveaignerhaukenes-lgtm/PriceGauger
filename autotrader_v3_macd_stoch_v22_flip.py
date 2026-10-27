"""MACD+Stoch V2.2 Flip: isolate the reversal decision from frozen V2.1.

An opposite strong composite from a *completed* bar immediately proposes the
opposite smallest legal inventory target. Existing Saxo V3 CLOSE->CONFIRM_FLAT
->OPEN, exact ownership, dedupe, precheck and margin caps are NEVER bypassed.
Weak/opposed evidence still proposes FLAT (never hold an adverse side).
Normal same-side build reuses the original V2.1 acceleration filter.
"""
from __future__ import annotations

from autotrader_v3_macd_stoch_v21 import macd_stoch_v21_target_v3
from autotrader_v3_macd_stoch_v2 import MacdStochV2DecisionV3, ENTRY_THRESHOLD
from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_trailing_v1 import MacdTrailingConfigV3

STRATEGY_KEY_V3 = "macd-stoch-v2-2-flip"
# One full closed-bar, strong-opposite reversal. Explicitly stronger than V2.1
# entry threshold to reduce one-bar spurious flip candidates.
FLIP_THRESHOLD = 0.30


def macd_stoch_v22_flip_target_v3(
    *, current_target: TargetInventoryV3, observation,
    previous_observation=None, bars=(),
    config: MacdTrailingConfigV3 = MacdTrailingConfigV3(),
) -> MacdStochV2DecisionV3:
    base = macd_stoch_v21_target_v3(
        current_target=current_target, observation=observation,
        previous_observation=previous_observation, bars=bars, config=config,
    )
    current = current_target.amount
    score = base.composite_score
    # V2.1 remains responsible for missing indicator data and all
    # non-reversing decisions; no speculative entry from missing evidence.
    if (base.action != "OPPOSITE_FLAT" or abs(current) < config.tranche / 2
            or abs(score) < max(FLIP_THRESHOLD, ENTRY_THRESHOLD)):
        return base
    side = 1 if score > 0 else -1
    if side * current >= 0:
        return base
    # A direct strategic target switch. The broker plan STILL closes first.
    return MacdStochV2DecisionV3(
        target=TargetInventoryV3(side * config.tranche),
        action="FLIP_TARGET",
        reason=base.reason + (
            f"; V2.2: one completed strong opposite bar "
            f"score={score:+.3f}, immediate opposite target; "
            "V3 Saxo CLOSE/CONFIRM_FLAT/OPEN remains mandatory"
        ),
        spread=base.spread,
        composite_score=base.composite_score,
        macd_component=base.macd_component,
        stoch_component=base.stoch_component,
    )


__all__ = ["STRATEGY_KEY_V3", "FLIP_THRESHOLD", "macd_stoch_v22_flip_target_v3"]
