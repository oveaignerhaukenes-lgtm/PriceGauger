from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_trailing_v1 import (
    MacdTrailingConfigV3,
    macd_trailing_target_v3,
)

STRATEGY_KEY_V3 = "macd-stoch-v1"


@dataclass(frozen=True, slots=True)
class MacdStochDecisionV3:
    target: TargetInventoryV3
    action: str
    reason: str
    spread: float
    stochastic_k: float
    stochastic_d: float


def _stochastic_k_series(bars: Sequence, period: int = 14) -> list[float]:
    if len(bars) < period:
        return []
    values: list[float] = []
    for index in range(period - 1, len(bars)):
        window = bars[index - period + 1:index + 1]
        high = max(float(item.high) for item in window)
        low = min(float(item.low) for item in window)
        close = float(bars[index].close)
        values.append(50.0 if high == low else 100.0 * (close - low) / (high - low))
    return values


def stochastic_kd_v3(bars: Sequence, *, period: int = 14, d_period: int = 3):
    """Return previous/current K,D from closed bars only; no look-ahead."""
    k = _stochastic_k_series(bars, period)
    if len(k) < d_period + 1:
        return None
    d = [sum(k[i-d_period+1:i+1]) / d_period for i in range(d_period - 1, len(k))]
    # d[j] corresponds to k[j + d_period - 1].
    current_k = k[-1]
    previous_k = k[-2]
    current_d = d[-1]
    previous_d = d[-2]
    return previous_k, previous_d, current_k, current_d


def macd_stoch_target_v3(
    *,
    current_target: TargetInventoryV3,
    observation,
    previous_observation=None,
    bars: Sequence = (),
    config: MacdTrailingConfigV3 = MacdTrailingConfigV3(),
) -> MacdStochDecisionV3:
    """MACD owns direction/build-up; an adverse Stoch K/D rollover may only flatten.

    Stochastic has FLAT authority, never opposite-direction authority. After a
    stochastic exit, MACD must rebuild exposure tranche-by-tranche on later bars.
    """
    kd = stochastic_kd_v3(bars)
    base = macd_trailing_target_v3(
        current_target=current_target,
        observation=observation,
        previous_observation=previous_observation,
        config=config,
    )
    if kd is None:
        return MacdStochDecisionV3(
            base.target, base.action, base.reason + "; stochastic warmup",
            float(observation.spread), 50.0, 50.0,
        )

    previous_k, previous_d, current_k, current_d = kd
    current = float(current_target.amount)
    bearish_rollover = previous_k >= previous_d and current_k < current_d
    bullish_rollover = previous_k <= previous_d and current_k > current_d

    if current > 0.0 and bearish_rollover:
        return MacdStochDecisionV3(
            TargetInventoryV3(0.0), "STOCH_FLAT_LONG",
            f"Stoch bearish rollover K {previous_k:.2f}->{current_k:.2f}, D {previous_d:.2f}->{current_d:.2f}; flatten LONG, never reverse",
            float(observation.spread), current_k, current_d,
        )
    if current < 0.0 and bullish_rollover:
        return MacdStochDecisionV3(
            TargetInventoryV3(0.0), "STOCH_FLAT_SHORT",
            f"Stoch bullish rollover K {previous_k:.2f}->{current_k:.2f}, D {previous_d:.2f}->{current_d:.2f}; flatten SHORT, never reverse",
            float(observation.spread), current_k, current_d,
        )

    return MacdStochDecisionV3(
        base.target, base.action,
        base.reason + f"; Stoch K={current_k:.2f} D={current_d:.2f} no adverse rollover",
        float(observation.spread), current_k, current_d,
    )


__all__ = ["STRATEGY_KEY_V3", "MacdStochDecisionV3", "stochastic_kd_v3", "macd_stoch_target_v3"]
