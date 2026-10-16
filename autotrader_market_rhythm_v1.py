"""Read-only multi-scale market rhythm analysis using confirmed price reversals.

Only completed, positive 1-minute closes are used. Turning points are recorded
at their historical pivot time but have a distinct `confirmed_at` when the
reversal threshold was crossed; they MUST NOT be traded at their pivot time.
Missing-minute gaps start a new independent segment.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from statistics import median, pstdev
from typing import Sequence

import pandas as pd


DEFAULT_THRESHOLDS_PCT = (0.05, 0.10, 0.25, 0.50, 1.00, 3.00)


@dataclass(frozen=True, slots=True)
class ConfirmedTurnV1:
    kind: str  # PEAK | TROUGH
    pivot_at: pd.Timestamp
    confirmed_at: pd.Timestamp
    price: float
    segment: int


@dataclass(frozen=True, slots=True)
class RhythmProfileV1:
    window: str
    threshold_pct: float
    observations: int
    confirmed_turns: int
    completed_legs: int
    completed_cycles: int
    median_leg_minutes: float | None
    median_cycle_minutes: float | None
    median_leg_amplitude_pct: float | None
    cycle_period_cv: float | None
    turns_per_hour: float
    leg_duration_1m: int
    leg_duration_2m: int
    leg_duration_3_to_4m: int
    leg_duration_5_to_8m: int
    leg_duration_over_8m: int


def _positive_1m_closes(price: pd.Series) -> pd.Series:
    clean = pd.to_numeric(price, errors="coerce").dropna()
    clean = clean[(clean > 0) & clean.map(lambda x: isfinite(float(x)))]
    if not isinstance(clean.index, pd.DatetimeIndex):
        raise ValueError("rhythm analysis requires a timestamp index")
    clean = clean.sort_index()
    if clean.index.has_duplicates:
        clean = clean[~clean.index.duplicated(keep="last")]
    return clean


def confirmed_turns_v1(price: pd.Series, *, reversal_pct: float) -> tuple[ConfirmedTurnV1, ...]:
    """Threshold-validated extrema, only *recognized* after adverse movement.

    A swing may be located at 12:00 and confirmed only at 12:03. Never leak the
    12:00 pivot into a 12:00 trade, regime label or strategy decision.
    """
    threshold = float(reversal_pct)
    if not isfinite(threshold) or threshold <= 0 or threshold >= 100:
        raise ValueError("reversal threshold must be in (0, 100) percent")
    clean = _positive_1m_closes(price)
    if len(clean) < 2:
        return ()
    times = list(clean.index)
    values = [float(x) for x in clean]
    result: list[ConfirmedTurnV1] = []
    epsilon = threshold / 100.0

    segment = 0
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and pd.Timedelta(0) < times[end] - times[end - 1] <= pd.Timedelta(seconds=90):
            end += 1
        if end - start < 2:
            start = end
            segment += 1
            continue

        low_index = high_index = start
        low = high = values[start]
        direction = 0
        extreme_index = start
        extreme_price = values[start]

        def record(kind: str, at_index: int, known_index: int) -> None:
            result.append(ConfirmedTurnV1(kind, times[at_index], times[known_index], values[at_index], segment))

        for i in range(start + 1, end):
            v = values[i]
            if direction == 0:
                if v < low:
                    low, low_index = v, i
                if v > high:
                    high, high_index = v, i
                if v >= low * (1 + epsilon):
                    record("TROUGH", low_index, i)
                    direction, extreme_index, extreme_price = 1, i, v
                elif v <= high * (1 - epsilon):
                    record("PEAK", high_index, i)
                    direction, extreme_index, extreme_price = -1, i, v
            elif direction == 1:
                if v > extreme_price:
                    extreme_price, extreme_index = v, i
                elif v <= extreme_price * (1 - epsilon):
                    record("PEAK", extreme_index, i)
                    direction, extreme_index, extreme_price = -1, i, v
            else:
                if v < extreme_price:
                    extreme_price, extreme_index = v, i
                elif v >= extreme_price * (1 + epsilon):
                    record("TROUGH", extreme_index, i)
                    direction, extreme_index, extreme_price = 1, i, v
        start = end
        segment += 1
    return tuple(result)


def market_rhythm_profile_v1(
    price: pd.Series,
    *,
    window: str,
    thresholds_pct: Sequence[float] = DEFAULT_THRESHOLDS_PCT,
) -> tuple[RhythmProfileV1, ...]:
    """Summarize confirmed half-cycle legs and full same-side cycles per scale.

    Raw price amplitude is based on the UNDERLYING, not leveraged account P/L.
    No fill costs or post-hoc optimal strategy switching is inferred.
    """
    clean = _positive_1m_closes(price)
    if len(clean) > 1:
        elapsed_hours = max((clean.index[-1] - clean.index[0]).total_seconds() / 3600.0, 1 / 60)
    else:
        elapsed_hours = 0
    profiles: list[RhythmProfileV1] = []
    for threshold in thresholds_pct:
        turns = confirmed_turns_v1(clean, reversal_pct=float(threshold))
        legs: list[tuple[float, float]] = []
        full_cycles: list[float] = []
        for idx, turn in enumerate(turns):
            if idx >= 1:
                prev = turns[idx - 1]
                if prev.segment == turn.segment and prev.kind != turn.kind:
                    duration = (turn.pivot_at - prev.pivot_at).total_seconds() / 60.0
                    if duration > 0:
                        amplitude = abs((turn.price / prev.price - 1.0) * 100.0)
                        legs.append((duration, amplitude))
            if idx >= 2:
                prev_same = turns[idx - 2]
                if prev_same.segment == turn.segment and prev_same.kind == turn.kind:
                    duration = (turn.pivot_at - prev_same.pivot_at).total_seconds() / 60.0
                    if duration > 0:
                        full_cycles.append(duration)
        periods = tuple(legs[i][0] for i in range(len(legs)))
        amps = tuple(legs[i][1] for i in range(len(legs)))
        cv = (pstdev(full_cycles) / (sum(full_cycles) / len(full_cycles))
              if len(full_cycles) >= 3 and sum(full_cycles) > 0 else None)
        profiles.append(RhythmProfileV1(
            window=str(window),
            threshold_pct=float(threshold),
            observations=len(clean),
            confirmed_turns=len(turns),
            completed_legs=len(legs),
            completed_cycles=len(full_cycles),
            median_leg_minutes=float(median(periods)) if periods else None,
            median_cycle_minutes=float(median(full_cycles)) if full_cycles else None,
            median_leg_amplitude_pct=float(median(amps)) if amps else None,
            cycle_period_cv=float(cv) if cv is not None else None,
            turns_per_hour=len(turns) / elapsed_hours if elapsed_hours else 0.0,
            leg_duration_1m=sum(d <= 1.0 for d in periods),
            leg_duration_2m=sum(1.0 < d <= 2.0 for d in periods),
            leg_duration_3_to_4m=sum(2.0 < d <= 4.0 for d in periods),
            leg_duration_5_to_8m=sum(4.0 < d <= 8.0 for d in periods),
            leg_duration_over_8m=sum(d > 8.0 for d in periods),
        ))
    return tuple(profiles)


__all__ = [
    "ConfirmedTurnV1", "DEFAULT_THRESHOLDS_PCT", "RhythmProfileV1",
    "confirmed_turns_v1", "market_rhythm_profile_v1",
]
