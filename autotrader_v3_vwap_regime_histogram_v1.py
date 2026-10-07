from __future__ import annotations

"""VWAP-regime + histogram exposure strategy for AutoTrader V3.

V1 deliberately keeps the hierarchy small:
- rolling volume-weighted VWAP slope owns directional authority;
- MACD histogram slope only scales exposure inside that authority;
- strong regime forbids counter-regime exposure;
- weak regime allows at most one counter-regime probe;
- flat regime holds no exposure and waits for a clearer regime.

The strategy consumes canonical 1m OHLCV bars for regime classification and the
configured closed-bar MACD observation for the fast exposure pulse.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Sequence

from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_histogram_v1 import (
    MacdHistogramConfigV3,
    MacdHistogramDecisionV3,
)

STRATEGY_KEY_V3 = "vwap-regime-histogram-v1"

VWAP_WINDOW_BARS_V3 = 10
ATR_WINDOW_BARS_V3 = 14
VWAP_WEAK_SLOPE_ATR_V3 = 0.20
VWAP_STRONG_SLOPE_ATR_V3 = 0.60
MIN_POSITIVE_VOLUME_BARS_V3 = 5

REGIME_STRONG_BULL = "STRONG_BULL"
REGIME_WEAK_BULL = "WEAK_BULL"
REGIME_FLAT = "FLAT"
REGIME_WEAK_BEAR = "WEAK_BEAR"
REGIME_STRONG_BEAR = "STRONG_BEAR"
REGIME_UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class VwapRegimeV3:
    regime: str
    slope_atr: float | None
    previous_vwap: float | None
    current_vwap: float | None
    atr: float | None


def _utc(value) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _q(value: float, tranche: float) -> float:
    quantized = round(float(value) / float(tranche)) * float(tranche)
    return 0.0 if abs(quantized) < float(tranche) / 2.0 else quantized


def _weighted_vwap(rows: Sequence) -> float | None:
    pv = 0.0
    volume_sum = 0.0
    positive = 0
    for row in rows:
        volume = getattr(row, "volume", None)
        if volume is None:
            continue
        volume = float(volume)
        if not isfinite(volume) or volume <= 0.0:
            continue
        high = float(row.high)
        low = float(row.low)
        close = float(row.close)
        typical = (high + low + close) / 3.0
        pv += typical * volume
        volume_sum += volume
        positive += 1
    if positive < MIN_POSITIVE_VOLUME_BARS_V3 or volume_sum <= 0.0:
        return None
    return pv / volume_sum


def _atr(rows: Sequence) -> float | None:
    if len(rows) < ATR_WINDOW_BARS_V3 + 1:
        return None
    sample = rows[-(ATR_WINDOW_BARS_V3 + 1):]
    ranges: list[float] = []
    for previous, current in zip(sample, sample[1:]):
        previous_close = float(previous.close)
        high = float(current.high)
        low = float(current.low)
        ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    value = sum(ranges) / len(ranges)
    return value if isfinite(value) and value > 0.0 else None


def classify_vwap_regime_v3(*, source_bars: Sequence, closed_at) -> VwapRegimeV3:
    """Classify local VWAP direction using two adjacent 10x1m volume windows.

    Slope is normalized by current 1m ATR so the thresholds remain meaningful as
    Tech100 volatility changes. Missing/zero volume fails to UNKNOWN rather than
    inventing a pseudo-VWAP from price alone.
    """

    cutoff = _utc(closed_at)
    eligible = sorted(
        (row for row in source_bars if _utc(row.bar_time) < cutoff),
        key=lambda row: _utc(row.bar_time),
    )
    needed = VWAP_WINDOW_BARS_V3 * 2
    if len(eligible) < max(needed, ATR_WINDOW_BARS_V3 + 1):
        return VwapRegimeV3(REGIME_UNKNOWN, None, None, None, None)

    previous_rows = eligible[-needed:-VWAP_WINDOW_BARS_V3]
    current_rows = eligible[-VWAP_WINDOW_BARS_V3:]
    previous_vwap = _weighted_vwap(previous_rows)
    current_vwap = _weighted_vwap(current_rows)
    atr = _atr(eligible)
    if previous_vwap is None or current_vwap is None or atr is None:
        return VwapRegimeV3(REGIME_UNKNOWN, None, previous_vwap, current_vwap, atr)

    slope_atr = (current_vwap - previous_vwap) / atr
    magnitude = abs(slope_atr)
    if magnitude < VWAP_WEAK_SLOPE_ATR_V3:
        regime = REGIME_FLAT
    elif slope_atr > 0:
        regime = REGIME_STRONG_BULL if magnitude >= VWAP_STRONG_SLOPE_ATR_V3 else REGIME_WEAK_BULL
    else:
        regime = REGIME_STRONG_BEAR if magnitude >= VWAP_STRONG_SLOPE_ATR_V3 else REGIME_WEAK_BEAR
    return VwapRegimeV3(regime, slope_atr, previous_vwap, current_vwap, atr)


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


def vwap_regime_histogram_target_v3(
    *,
    current_target: TargetInventoryV3,
    observation,
    previous_observation=None,
    source_bars: Sequence = (),
    config: MacdHistogramConfigV3 = MacdHistogramConfigV3(),
) -> MacdHistogramDecisionV3:
    current = _q(current_target.amount, config.tranche)
    regime = classify_vwap_regime_v3(
        source_bars=source_bars,
        closed_at=getattr(observation, "closed_at", observation.bar_time),
    )
    pulse = _pulse(observation, previous_observation)
    tranche = float(config.tranche)
    maximum = float(config.max_inventory)

    if regime.regime == REGIME_UNKNOWN:
        target = current
        policy = "VWAP unavailable -> HOLD"
    elif regime.regime == REGIME_FLAT:
        target = 0.0
        policy = "flat VWAP -> FLAT and wait"
    elif regime.regime == REGIME_STRONG_BULL:
        if current < 0.0:
            target = 0.0
            policy = "strong bull forbids SHORT -> FLAT"
        elif pulse > 0:
            target = min(maximum, current + tranche)
            policy = "strong bull + rising histogram -> build LONG"
        elif pulse < 0:
            target = max(0.0, current - tranche)
            policy = "strong bull + falling histogram -> reduce LONG"
        else:
            target = current
            policy = "strong bull + flat histogram -> HOLD"
    elif regime.regime == REGIME_STRONG_BEAR:
        if current > 0.0:
            target = 0.0
            policy = "strong bear forbids LONG -> FLAT"
        elif pulse < 0:
            target = max(-maximum, current - tranche)
            policy = "strong bear + falling histogram -> build SHORT"
        elif pulse > 0:
            target = min(0.0, current + tranche)
            policy = "strong bear + rising histogram -> reduce SHORT"
        else:
            target = current
            policy = "strong bear + flat histogram -> HOLD"
    elif regime.regime == REGIME_WEAK_BULL:
        if pulse > 0:
            target = min(0.0, current + tranche) if current < 0.0 else min(maximum, current + tranche)
            policy = "weak bull + rising histogram -> reduce SHORT/build LONG"
        elif pulse < 0:
            if current > 0.0:
                target = max(0.0, current - tranche)
            elif current == 0.0:
                target = -tranche
            else:
                target = max(-tranche, current)
            policy = "weak bull + falling histogram -> reduce LONG/allow one SHORT probe"
        else:
            target = current
            policy = "weak bull + flat histogram -> HOLD"
    else:  # REGIME_WEAK_BEAR
        if pulse < 0:
            target = max(0.0, current - tranche) if current > 0.0 else max(-maximum, current - tranche)
            policy = "weak bear + falling histogram -> reduce LONG/build SHORT"
        elif pulse > 0:
            if current < 0.0:
                target = min(0.0, current + tranche)
            elif current == 0.0:
                target = tranche
            else:
                target = min(tranche, current)
            policy = "weak bear + rising histogram -> reduce SHORT/allow one LONG probe"
        else:
            target = current
            policy = "weak bear + flat histogram -> HOLD"

    target = _q(max(-maximum, min(maximum, target)), tranche)
    score = "n/a" if regime.slope_atr is None else f"{regime.slope_atr:+.3f} ATR"
    reason = f"VWAP {regime.regime} slope={score}; {policy}"
    return MacdHistogramDecisionV3(
        target=TargetInventoryV3(target),
        action=_action(current, target),
        reason=reason,
        histogram=float(observation.spread),
    )


__all__ = [
    "STRATEGY_KEY_V3",
    "VwapRegimeV3",
    "classify_vwap_regime_v3",
    "vwap_regime_histogram_target_v3",
]
