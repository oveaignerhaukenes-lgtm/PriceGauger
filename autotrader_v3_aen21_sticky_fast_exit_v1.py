from __future__ import annotations

"""Aen#2.1: Aen#2 sticky regime with fast exit on raw R sign reversal.

This variant preserves Aen#2's sticky build/reduce behavior and adaptive
deadband for *new* directional authority, but it does not allow the deadband
to keep an existing position on the wrong side of a raw regime MACD cross.

Exit is therefore faster than re-entry:
- SHORT + raw R spread > 0 -> FLAT immediately.
- LONG + raw R spread < 0 -> FLAT immediately.
- Re-entry/build in the new direction still requires the ordinary Aen#2
  deadband-confirmed regime and S confirmation.
"""

from typing import Sequence

from autotrader_v3_aen2_sticky_regime_v1 import (
    aen2_sticky_regime_target_v3,
    classify_sticky_regime_v3,
)
from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_histogram_v1 import (
    MacdHistogramConfigV3,
    MacdHistogramDecisionV3,
)

STRATEGY_KEY_V3 = "aen21-sticky-fast-exit-v1"


def _q(value: float, tranche: float) -> float:
    quantized = round(float(value) / float(tranche)) * float(tranche)
    return 0.0 if abs(quantized) < float(tranche) / 2.0 else quantized


def aen21_sticky_fast_exit_target_v3(
    *,
    current_target: TargetInventoryV3,
    observation,
    previous_observation=None,
    source_bars: Sequence = (),
    regime_timeframe_minutes: int = 15,
    market_name: str = "",
    config: MacdHistogramConfigV3 = MacdHistogramConfigV3(),
) -> MacdHistogramDecisionV3:
    """Aen#2 with raw-R wrong-side exit before deadband-confirmed re-entry."""

    current = _q(current_target.amount, config.tranche)
    closed_at = getattr(observation, "closed_at", observation.bar_time)
    regime = classify_sticky_regime_v3(
        source_bars=source_bars,
        closed_at=closed_at,
        regime_timeframe_minutes=int(regime_timeframe_minutes),
        market_name=str(market_name),
    )

    raw_spread = regime.spread
    if raw_spread is not None and current < 0.0 and float(raw_spread) > 0.0:
        return MacdHistogramDecisionV3(
            target=TargetInventoryV3(0.0),
            action="FLAT",
            reason=(
                f"Aen#2.1 raw R{regime.timeframe_minutes}m spread "
                f"{float(raw_spread):+.6g} crossed against SHORT -> FAST EXIT; "
                "deadband still governs re-entry"
            ),
            histogram=float(observation.spread),
        )

    if raw_spread is not None and current > 0.0 and float(raw_spread) < 0.0:
        return MacdHistogramDecisionV3(
            target=TargetInventoryV3(0.0),
            action="FLAT",
            reason=(
                f"Aen#2.1 raw R{regime.timeframe_minutes}m spread "
                f"{float(raw_spread):+.6g} crossed against LONG -> FAST EXIT; "
                "deadband still governs re-entry"
            ),
            histogram=float(observation.spread),
        )

    decision = aen2_sticky_regime_target_v3(
        current_target=current_target,
        observation=observation,
        previous_observation=previous_observation,
        source_bars=source_bars,
        regime_timeframe_minutes=regime_timeframe_minutes,
        market_name=market_name,
        config=config,
    )
    return MacdHistogramDecisionV3(
        target=decision.target,
        action=decision.action,
        reason=f"Aen#2.1 delegated sticky policy; {decision.reason}",
        histogram=decision.histogram,
    )


__all__ = ["STRATEGY_KEY_V3", "aen21_sticky_fast_exit_target_v3"]
