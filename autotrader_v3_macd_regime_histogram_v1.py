from __future__ import annotations

"""MACD regime + histogram exposure strategy for AutoTrader V3.

R = configurable higher-timeframe MACD regime.
S = configurable signal/exposure timeframe (the ordinary V3 timeframe setting).

The R timeframe owns directional authority. The S histogram slope may only build,
reduce or flatten exposure on that authorised side. It cannot open exposure against
the R regime.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from autotrader_mtf_entry_shadow_v2 import closed_bars_v2, macd_observations_v2
from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_histogram_v1 import (
    MacdHistogramConfigV3,
    MacdHistogramDecisionV3,
)

STRATEGY_KEY_V3 = "macd-regime-histogram-v1"

REGIME_BULL = "BULL"
REGIME_NEUTRAL = "NEUTRAL"
REGIME_BEAR = "BEAR"
REGIME_UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class MacdRegimeV3:
    regime: str
    spread: float | None
    timeframe_minutes: int


def _utc(value) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(
        str(value).replace("Z", "+00:00")
    )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _q(value: float, tranche: float) -> float:
    quantized = round(float(value) / float(tranche)) * float(tranche)
    return 0.0 if abs(quantized) < float(tranche) / 2.0 else quantized


def classify_macd_regime_v3(
    *,
    source_bars: Sequence,
    closed_at,
    regime_timeframe_minutes: int,
    market_name: str,
) -> MacdRegimeV3:
    """Resolve the latest fully closed R-timeframe MACD regime at signal close."""

    cutoff = _utc(closed_at)
    points = tuple(
        item.point
        for item in source_bars
        if _utc(item.bar_time) < cutoff
    )
    if not points:
        return MacdRegimeV3(REGIME_UNKNOWN, None, int(regime_timeframe_minutes))

    closed = closed_bars_v2(
        points,
        market=str(market_name),
        timeframe_minutes=int(regime_timeframe_minutes),
    )
    observations = macd_observations_v2(
        closed,
        timeframe_minutes=int(regime_timeframe_minutes),
    ) if closed else ()
    eligible = tuple(
        item for item in observations
        if _utc(item.closed_at) <= cutoff
    )
    if not eligible:
        return MacdRegimeV3(REGIME_UNKNOWN, None, int(regime_timeframe_minutes))

    spread = float(eligible[-1].spread)
    if spread > 0.0:
        regime = REGIME_BULL
    elif spread < 0.0:
        regime = REGIME_BEAR
    else:
        regime = REGIME_NEUTRAL
    return MacdRegimeV3(regime, spread, int(regime_timeframe_minutes))


def _pulse(observation, previous_observation) -> int:
    current = float(observation.spread)
    if previous_observation is None:
        return 1 if current > 0.0 else (-1 if current < 0.0 else 0)
    previous = float(previous_observation.spread)
    return 1 if current > previous else (-1 if current < previous else 0)


def _action(current: float, target: float) -> str:
    if target == current:
        return "HOLD"
    if target == 0.0:
        return "FLAT"
    if current == 0.0:
        return "OPEN"
    if (current > 0.0) != (target > 0.0):
        return "CROSS_ZERO"
    return "BUILD" if abs(target) > abs(current) else "REDUCE"


def macd_regime_histogram_target_v3(
    *,
    current_target: TargetInventoryV3,
    observation,
    previous_observation=None,
    source_bars: Sequence = (),
    regime_timeframe_minutes: int = 15,
    market_name: str = "",
    config: MacdHistogramConfigV3 = MacdHistogramConfigV3(),
) -> MacdHistogramDecisionV3:
    """R timeframe owns side; S histogram slope owns exposure."""

    current = _q(current_target.amount, config.tranche)
    regime = classify_macd_regime_v3(
        source_bars=source_bars,
        closed_at=getattr(observation, "closed_at", observation.bar_time),
        regime_timeframe_minutes=int(regime_timeframe_minutes),
        market_name=str(market_name),
    )
    pulse = _pulse(observation, previous_observation)
    tranche = float(config.tranche)
    maximum = float(config.max_inventory)

    if regime.regime == REGIME_UNKNOWN:
        target = current
        policy = "R MACD unavailable -> HOLD"
    elif regime.regime == REGIME_NEUTRAL:
        target = 0.0
        policy = "R MACD neutral -> FLAT"
    elif regime.regime == REGIME_BULL:
        if current < 0.0:
            target = 0.0
            policy = "R BULL forbids SHORT -> FLAT"
        elif pulse > 0:
            target = min(maximum, current + tranche)
            policy = "R BULL + S histogram rising -> build LONG"
        elif pulse < 0:
            target = max(0.0, current - tranche)
            policy = "R BULL + S histogram falling -> reduce LONG"
        else:
            target = current
            policy = "R BULL + S histogram flat -> HOLD"
    else:  # REGIME_BEAR
        if current > 0.0:
            target = 0.0
            policy = "R BEAR forbids LONG -> FLAT"
        elif pulse < 0:
            target = max(-maximum, current - tranche)
            policy = "R BEAR + S histogram falling -> build SHORT"
        elif pulse > 0:
            target = min(0.0, current + tranche)
            policy = "R BEAR + S histogram rising -> reduce SHORT"
        else:
            target = current
            policy = "R BEAR + S histogram flat -> HOLD"

    target = _q(max(-maximum, min(maximum, target)), tranche)
    regime_spread = "n/a" if regime.spread is None else f"{regime.spread:+.6g}"
    reason = (
        f"MACD-R{regime.timeframe_minutes}m {regime.regime} spread={regime_spread}; "
        f"{policy}"
    )
    return MacdHistogramDecisionV3(
        target=TargetInventoryV3(target),
        action=_action(current, target),
        reason=reason,
        histogram=float(observation.spread),
    )


__all__ = [
    "STRATEGY_KEY_V3",
    "MacdRegimeV3",
    "classify_macd_regime_v3",
    "macd_regime_histogram_target_v3",
]
