"""MACD + Stochastic v2: one normalized, weighted momentum signal.

Unlike macd-stoch-v1 (MACD owns direction, Stochastic may only flatten),
this strategy combines two signed components into a continuous score:

    composite = 0.70 * tanh(2 * MACD_histogram / ATR14)
              + 0.30 * tanh((stochastic_K - stochastic_D) / 20).

An entry requires confirmation from two closed bars; weak composite momentum
does not cause a new entry; an adverse score first sends the position FLAT.
No broker calls, independent of Saxo/V3 execution and account permissions.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, tanh
from typing import Sequence

from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_stoch_v1 import stochastic_kd_v3
from autotrader_v3_macd_trailing_v1 import MacdTrailingConfigV3

STRATEGY_KEY_V3 = "macd-stoch-v2"
MACD_WEIGHT = 0.70
STOCH_WEIGHT = 0.30
ENTRY_THRESHOLD = 0.22
EXIT_THRESHOLD = 0.10
STOCH_SCALE = 20.0
ATR_MULTIPLIER = 2.0
ATR_PERIOD = 14


@dataclass(frozen=True, slots=True)
class MacdStochV2DecisionV3:
    target: TargetInventoryV3
    action: str
    reason: str
    spread: float
    composite_score: float = 0.0
    macd_component: float = 0.0
    stoch_component: float = 0.0


def _atr_price_points(bars: Sequence, period: int = ATR_PERIOD) -> float | None:
    if len(bars) < period + 1:
        return None
    values = []
    for idx in range(len(bars) - period, len(bars)):
        current = bars[idx]
        prev_close = float(bars[idx - 1].close)
        high, low = float(current.high), float(current.low)
        if not all(isfinite(v) for v in (high, low, prev_close)) or low > high:
            return None
        values.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    scale = sum(values) / period
    return scale if isfinite(scale) and scale > 0 else None


def composite_score_v3(observation, bars: Sequence):
    """Return signed score and components for fully CLOSED matching-timeframe bars.

    Uses MACD histogram in price points, ATR in price points, K-D in
    Stochastic points. No future candle, account state or global history.
    """
    atr = _atr_price_points(bars)
    kd = stochastic_kd_v3(bars)
    if atr is None or kd is None:
        return None
    hist = float(observation.spread)
    if not isfinite(hist):
        return None
    k_minus_d = float(kd[2] - kd[3])
    if not isfinite(k_minus_d):
        return None
    macd = tanh(ATR_MULTIPLIER * hist / atr)
    stoch = tanh(k_minus_d / STOCH_SCALE)
    return MACD_WEIGHT * macd + STOCH_WEIGHT * stoch, macd, stoch


def macd_stoch_v2_target_v3(
    *,
    current_target: TargetInventoryV3,
    observation,
    previous_observation=None,
    bars: Sequence = (),
    config: MacdTrailingConfigV3 = MacdTrailingConfigV3(),
) -> MacdStochV2DecisionV3:
    """Weighted MACD/Stoch score with anti-churn deadband and confirmed entries.

    When momentum crosses against current exposure, flatten first; only the
    NEXT closed bar can open the new side. Never directly flip +/- inventory.
    """
    spread = float(observation.spread)
    current = round(float(current_target.amount) / config.tranche) * config.tranche
    current = 0.0 if abs(current) < config.tranche / 2 else round(current, 10)
    now = composite_score_v3(observation, bars)
    before = (composite_score_v3(previous_observation, bars[:-1])
              if previous_observation is not None else None)

    if now is None:
        return MacdStochV2DecisionV3(
            TargetInventoryV3(0.0), "FLAT_WARMUP",
            "MACD+Stoch v2: missing finite ATR14/Stochastic K-D evidence; fail flat",
            spread)
    score, macd, stoch = now
    detail = (f"composite={score:+.3f}; MACD={macd:+.3f} × 0.70; "
              f"Stoch K-D={stoch:+.3f} × 0.30")

    def decision(target: float, action: str, why: str):
        return MacdStochV2DecisionV3(
            TargetInventoryV3(round(target, 10)), action,
            detail + "; " + why, spread, score, macd, stoch)

    # Existing inventory cannot remain opposed to the composite sign,
    # nor be trailed slowly through a near-zero score.
    if current != 0.0 and current * score <= 0.0:
        return decision(0.0, "OPPOSITE_FLAT", "opposite composite signal; flatten before reversing")
    if abs(score) <= EXIT_THRESHOLD:
        return decision(0.0, "WEAK_FLAT", "inside exit deadband; suppress noise exposure")
    if abs(score) < ENTRY_THRESHOLD:
        return decision(current, "HOLD_WEAK", "momentum insufficient for added exposure")
    if before is None:
        return decision(current, "WAIT_CONFIRMATION", "no prior closed-bar composite score")
    prior_score = before[0]
    if score * prior_score <= 0 or abs(prior_score) < ENTRY_THRESHOLD:
        return decision(current, "WAIT_CONFIRMATION", "need two aligned closed-bar signals")
    side = 1.0 if score > 0 else -1.0
    if current * side < 0:
        return decision(0.0, "OPPOSITE_FLAT", "flatten current side before new entry")

    next_size = min(config.max_inventory, abs(current) + config.tranche)
    target = side * round(next_size / config.tranche) * config.tranche
    bounded = min(config.max_inventory, abs(target))
    target = side * round(bounded / config.tranche) * config.tranche
    target = round(target, 10)
    if target == current:
        return decision(current, "HOLD_MAX", "max exposure reached")
    return decision(target, "OPEN" if current == 0 else "BUILD", "confirmed composite momentum; one tranche")


__all__ = ["STRATEGY_KEY_V3", "MacdStochV2DecisionV3",
           "composite_score_v3", "macd_stoch_v2_target_v3"]
