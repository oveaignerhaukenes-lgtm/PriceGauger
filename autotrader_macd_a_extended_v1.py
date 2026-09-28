"""Extended MACD-A 1–30 minute signal selection, pure shadow planner.

Preserves legacy MACD-A unchanged. The existing adaptive 1/2/5m selector owns
direction. Closed 15/30m MACD adds regime context; it never overrides or vetoes
the fast direction. This prevents stale slow-bar reversals from forcing a trade.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Mapping

from autotrader_macd_models_v1 import adaptive_timeframe_v1

STRATEGY_KEY = "macd-a-1-30-v1"
PYRAMID_STRATEGY_KEY = "macd-a-pyr-1-30-v1"
TIMEFRAMES = (1, 2, 5, 15, 30)


@dataclass(frozen=True)
class ExtendedMacdADecision:
    direction: str
    selected_minutes: int
    confirmed_minutes: tuple[int, ...]
    opposing_minutes: tuple[int, ...]
    regime: str


def select_extended_macd_a(
    spreads: Mapping[int, float],
    *,
    micro_edge: float,
    noise: float,
) -> ExtendedMacdADecision:
    """Select adaptive fast direction and report longer-timeframe agreement.

    Input spreads must be from the latest *closed* bar for each timeframe.
    Missing slow frames do not change the original MACD-A direction.
    """
    if any(m not in spreads for m in (1, 2, 5)):
        raise ValueError("1/2/5m closed MACD spreads required")
    if any(not isfinite(float(v)) for v in spreads.values()):
        raise ValueError("non-finite MACD spread")
    if not all(isfinite(float(x)) and 0 <= float(x) <= 1 for x in (micro_edge, noise)):
        raise ValueError("micro_edge/noise must be finite and normalized")
    selected = adaptive_timeframe_v1(micro_edge=micro_edge, noise=noise)
    value = float(spreads[selected])
    direction = "LONG" if value > 0 else "SHORT" if value < 0 else "FLAT"
    aligned = tuple(m for m in TIMEFRAMES if m in spreads and direction != "FLAT" and float(spreads[m]) * value > 0)
    opposing = tuple(m for m in TIMEFRAMES if m in spreads and direction != "FLAT" and float(spreads[m]) * value < 0)
    slow_aligned = sum(m in aligned for m in (15, 30))
    regime = "STRONG_ALIGNMENT" if slow_aligned == 2 else "PARTIAL_ALIGNMENT" if slow_aligned == 1 else "UNCONFIRMED"
    return ExtendedMacdADecision(direction, selected, aligned, opposing, regime)


__all__ = ["STRATEGY_KEY", "PYRAMID_STRATEGY_KEY", "TIMEFRAMES", "ExtendedMacdADecision", "select_extended_macd_a"]
