"""RytmeTrend#1: 15m regime, complete 5m structure, confirmed 1m rhythm.

Pure deterministic target logic. Input is historical fully closed canonical
bars. Never uses future pivots, Saxo endpoints or mutable account state.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Sequence

from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_histogram_v1 import MacdHistogramConfigV3, MacdHistogramDecisionV3
from autotrader_v3_aen2_sticky_regime_v1 import (
    classify_sticky_regime_v3, REGIME_BULL, REGIME_BEAR,
)
from autotrader_v3_macd_stoch_rhythm_build_v1 import rhythm_build_evidence_v1

STRATEGY_KEY_V3 = "rhythm-trend-1-v1"
MESO_MINUTES = 5
MAX_TRANCHES = 3
MAX_BARS = 2100


def _utc(raw):
    v = raw if isinstance(raw, datetime) else datetime.fromisoformat(
        str(raw).replace("Z", "+00:00"))
    return (v.replace(tzinfo=timezone.utc) if v.tzinfo is None else
            v.astimezone(timezone.utc))


@dataclass(frozen=True, slots=True)
class MesoStructureV1:
    available: bool
    direction: int   # +1 HH/HL, -1 LL/LH, 0 unconfirmed


def complete_buckets_v1(source_bars: Sequence, cutoff, minutes: int, count: int):
    """Construct exactly complete OHLC buckets; missing/duplicate minute fails.

    All timestamps are UTC, aligned to epoch. Only source bars with start
    strictly before the decision cutoff can contribute.
    """
    end = _utc(cutoff)
    if end.second or end.microsecond:
        return ()
    end -= timedelta(minutes=end.minute % minutes)
    start = end - timedelta(minutes=minutes * count)
    found = {}
    for bar in source_bars[-MAX_BARS:]:
        try:
            stamp = _utc(bar.bar_time)
            if stamp < start or stamp >= end:
                continue
            values = tuple(float(getattr(bar, k)) for k in ("open", "high", "low", "close"))
            op, hi, lo, cl = values
            if stamp.second or stamp.microsecond or stamp in found:
                return ()
            if not all(isfinite(x) and x > 0 for x in values) or not (lo <= op <= hi and lo <= cl <= hi):
                return ()
            found[stamp] = (op, hi, lo, cl)
        except (TypeError, ValueError, OverflowError, AttributeError):
            return ()
    aggregate = []
    for i in range(count):
        base = start + timedelta(minutes=i * minutes)
        rows = [found.get(base + timedelta(minutes=j)) for j in range(minutes)]
        if any(x is None for x in rows):
            return ()
        aggregate.append((rows[0][0], max(x[1] for x in rows),
                          min(x[2] for x in rows), rows[-1][3]))
    return tuple(aggregate)


def meso_structure_v1(source_bars: Sequence, *, closed_at) -> MesoStructureV1:
    blocks = complete_buckets_v1(source_bars, closed_at, MESO_MINUTES, 3)
    if not blocks:
        return MesoStructureV1(False, 0)
    h = [b[1] for b in blocks]
    l = [b[2] for b in blocks]
    c = [b[3] for b in blocks]
    if h[2] > h[1] > h[0] and l[2] > l[1] > l[0] and c[2] > c[1]:
        return MesoStructureV1(True, 1)
    if h[2] < h[1] < h[0] and l[2] < l[1] < l[0] and c[2] < c[1]:
        return MesoStructureV1(True, -1)
    return MesoStructureV1(True, 0)


def rhythm_trend_target_v3(
    *, current_target: TargetInventoryV3, observation,
    previous_observation=None, bars: Sequence = (), source_bars: Sequence = (),
    regime_timeframe_minutes: int = 15, market_name: str = "",
    config: MacdHistogramConfigV3 = MacdHistogramConfigV3(),
) -> MacdHistogramDecisionV3:
    """Exits first; no direct +/- flip; no buildup in chop or data gaps.

    On sustained alignment, enter at minimum size, build at most once
    per completed 5m boundary and never beyond three Saxo legal tranches.
    """
    del previous_observation
    if int(regime_timeframe_minutes) != 15:
        raise ValueError("RytmeTrend requires a 15m macro regime")
    tranche = float(config.tranche)
    maximum = min(float(config.max_inventory), tranche * MAX_TRANCHES)
    if not (isfinite(tranche) and tranche > 0 and isfinite(maximum)
            and maximum >= tranche):
        raise ValueError("invalid instrument tranche/cap")
    current = round(float(current_target.amount) / tranche) * tranche
    current = 0.0 if abs(current) < tranche / 2 else round(current, 10)
    cutoff = _utc(getattr(observation, "closed_at",
                          _utc(observation.bar_time) + timedelta(minutes=1)))
    histogram = float(observation.spread)

    def result(target, action, why):
        return MacdHistogramDecisionV3(
            TargetInventoryV3(round(float(target), 10)), action,
            "RytmeTrend#1 R15/S5/M1: " + why, histogram)

    def keep_small(why):
        if abs(current) > tranche + 1e-9:
            return result((1 if current > 0 else -1) * tranche, "TRIM", why)
        return result(current, "HOLD", why)

    micro = rhythm_build_evidence_v1(
        bars, observation_time=observation.bar_time)
    if not micro.available:
        return result(0, "FLAT" if current else "HOLD",
                      "incomplete contiguous 1m input -> safe FLAT")

    if not complete_buckets_v1(source_bars, cutoff, 15, 1):
        return result(0, "FLAT" if current else "HOLD",
                      "incomplete latest confirmed 15m candle -> FLAT")
    macro = classify_sticky_regime_v3(
        source_bars=source_bars[-MAX_BARS:], closed_at=cutoff,
        regime_timeframe_minutes=15, market_name=str(market_name))
    if macro.regime not in (REGIME_BULL, REGIME_BEAR):
        return result(0, "FLAT" if current else "HOLD",
                      "unknown/neutral 15m MACD regime -> FLAT")
    side = 1 if macro.regime == REGIME_BULL else -1
    if current and current * side < 0:
        return result(0, "FLAT", "opposite 15m regime -> FULL FLAT first")

    meso = meso_structure_v1(source_bars, closed_at=cutoff)
    if not meso.available:
        return result(0, "FLAT" if current else "HOLD",
                      "incomplete 5m price structure -> FLAT")
    if current and current * meso.direction < 0:
        return result(0, "FLAT", "opposite confirmed 5m structure -> FULL FLAT")
    if meso.direction != side:
        return keep_small("5m HH/HL or LL/LH not confirmed -> one tranche")
    if micro.choppy or micro.confirmed_direction != side:
        return keep_small("1m rhythm choppy/unconfirmed -> one tranche")
    if abs(current) > maximum + 1e-9:
        return result(side * maximum, "TRIM", "above three-tranche cap")
    if not current:
        return result(side * tranche, "OPEN", "R15/S5/M1 aligned: minimum entry")
    if cutoff.minute % MESO_MINUTES:
        return result(current, "HOLD", "await next completed 5m bar")
    if abs(current) >= maximum - 1e-9:
        return result(current, "HOLD", "at three-tranche cap")
    return result(side * min(maximum, abs(current) + tranche), "BUILD",
                  "R15/S5/M1 aligned, new closed 5m bar: add one tranche")


__all__ = ["STRATEGY_KEY_V3", "MesoStructureV1",
           "complete_buckets_v1", "meso_structure_v1",
           "rhythm_trend_target_v3", "MAX_TRANCHES"]
