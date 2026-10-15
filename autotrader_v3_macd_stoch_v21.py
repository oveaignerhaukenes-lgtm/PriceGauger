"""MACD+Stoch V2.1: isolate one change from frozen V2 baseline.

Keep V2's first-entry threshold, opposite/weak FLAT, hold deadband and
closed-bar evidence unchanged. ONLY additional requirement for subsequent
BUILD is that the signed composite's magnitude grows by more than 0.02
from the preceding fully closed bar. No Saxo calls or direct LIVE actions.
"""
from __future__ import annotations

from autotrader_v3_macd_stoch_v2 import (
    MacdStochV2DecisionV3, composite_score_v3, macd_stoch_v2_target_v3,
)
from autotrader_v3_macd_trailing_v1 import MacdTrailingConfigV3
from autotrader_v3_domain import TargetInventoryV3

STRATEGY_KEY_V3 = "macd-stoch-v2-1"
BUILD_SCORE_DELTA = 0.02


def macd_stoch_v21_target_v3(
    *,
    current_target: TargetInventoryV3,
    observation,
    previous_observation=None,
    bars=(),
    config: MacdTrailingConfigV3 = MacdTrailingConfigV3(),
) -> MacdStochV2DecisionV3:
    """Keep every V2 decision except BUILD when momentum isn't accelerating."""
    base = macd_stoch_v2_target_v3(
        current_target=current_target,
        observation=observation,
        previous_observation=previous_observation,
        bars=bars,
        config=config,
    )
    if base.action != "BUILD":
        return base

    prior = (
        composite_score_v3(previous_observation, bars[:-1])
        if previous_observation is not None else None
    )
    if prior is None:
        # Fail-closed on missing prior evidence: do not increase broker target.
        delta = None
    else:
        delta = abs(base.composite_score) - abs(prior[0])
    if delta is not None and delta > BUILD_SCORE_DELTA:
        return base

    current = TargetInventoryV3(current_target.amount)
    note = (
        "missing previous composite evidence"
        if delta is None else
        f"composite magnitude growth {delta:+.3f} <= {BUILD_SCORE_DELTA:.3f}"
    )
    return MacdStochV2DecisionV3(
        target=current,
        action="HOLD_BUILD_DECELERATING",
        reason=base.reason + "; V2.1: " + note + "; no new tranche",
        spread=base.spread,
        composite_score=base.composite_score,
        macd_component=base.macd_component,
        stoch_component=base.stoch_component,
    )


__all__ = ["STRATEGY_KEY_V3", "BUILD_SCORE_DELTA", "macd_stoch_v21_target_v3"]
