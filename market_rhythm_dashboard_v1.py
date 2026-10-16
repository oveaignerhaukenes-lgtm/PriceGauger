"""Read-only, causally dated market-rhythm projections for the Markedsrytme page.

Uses existing canonical 1-minute closes only. Pivot timestamps describe hindsight
extrema; confirmation timestamps define earliest actionable knowledge.
No Saxo/execution imports and no persistence.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Sequence

import pandas as pd

from autotrader_market_rhythm_v1 import (
    DEFAULT_THRESHOLDS_PCT,
    ConfirmedTurnV1,
    RhythmProfileV1,
    confirmed_turns_v1,
    market_rhythm_profile_v1,
)


DURATION_BUCKETS = ("1m", "2m", "3–4m", "5–8m", "9–20m", ">20m")


@dataclass(frozen=True)
class SwingLegV1:
    threshold_pct: float
    start_at: pd.Timestamp
    end_at: pd.Timestamp
    confirmed_at: pd.Timestamp
    direction: str
    duration_minutes: float
    amplitude_pct: float
    speed_pct_per_min: float


@dataclass(frozen=True)
class RhythmViewV1:
    as_of: pd.Timestamp | None
    prices: pd.Series
    profiles: tuple[RhythmProfileV1, ...]
    turns: dict[float, tuple[ConfirmedTurnV1, ...]]
    legs: tuple[SwingLegV1, ...]


def build_rhythm_view_v1(
    prices: pd.Series, *,
    window: str = "24t",
    thresholds_pct: Sequence[float] = DEFAULT_THRESHOLDS_PCT,
) -> RhythmViewV1:
    """Historical descriptive profile, never a claim about future turning points."""
    clean = pd.to_numeric(prices, errors="coerce").dropna()
    if not isinstance(clean.index, pd.DatetimeIndex):
        raise ValueError("market rhythm requires DatetimeIndex")
    clean = clean[(clean > 0) & (clean < float("inf"))].sort_index()
    clean = clean[~clean.index.duplicated(keep="last")]
    clean.index = pd.to_datetime(clean.index, utc=True)

    profiles = market_rhythm_profile_v1(
        clean, window=window, thresholds_pct=tuple(thresholds_pct)
    )
    turns: dict[float, tuple[ConfirmedTurnV1, ...]] = {}
    legs: list[SwingLegV1] = []
    for threshold in thresholds_pct:
        key = float(threshold)
        events = confirmed_turns_v1(clean, reversal_pct=key)
        turns[key] = events
        for previous, current in zip(events, events[1:]):
            if previous.segment != current.segment or previous.kind == current.kind:
                continue
            minutes = (current.pivot_at - previous.pivot_at).total_seconds() / 60.0
            if minutes <= 0 or previous.price <= 0:
                continue
            pct = (current.price / previous.price - 1.0) * 100.0
            legs.append(SwingLegV1(
                threshold_pct=key,
                start_at=previous.pivot_at,
                end_at=current.pivot_at,
                confirmed_at=current.confirmed_at,
                direction="OPP" if pct > 0 else "NED",
                duration_minutes=minutes,
                amplitude_pct=abs(pct),
                speed_pct_per_min=abs(pct) / minutes,
            ))
    return RhythmViewV1(
        as_of=clean.index[-1] if len(clean) else None,
        prices=clean,
        profiles=profiles,
        turns=turns,
        legs=tuple(legs),
    )


def duration_bucket_v1(minutes: float) -> str:
    if minutes <= 1:
        return "1m"
    if minutes <= 2:
        return "2m"
    if minutes <= 4:
        return "3–4m"
    if minutes <= 8:
        return "5–8m"
    if minutes <= 20:
        return "9–20m"
    return ">20m"


def last_confirmed_legs_v1(
    view: RhythmViewV1, *, threshold_pct: float, limit: int = 12,
) -> list[dict[str, object]]:
    """A completed leg is listed only once its *ending* turn is confirmed."""
    relevant = (leg for leg in view.legs if leg.threshold_pct == threshold_pct)
    result = [
        {
            "Fra": leg.start_at,
            "Til": leg.end_at,
            "Bekreftet": leg.confirmed_at,
            "Retning": leg.direction,
            "Minutter": round(leg.duration_minutes, 2),
            "Amplitude %": round(leg.amplitude_pct, 3),
            "Hastighet %/min": round(leg.speed_pct_per_min, 4),
        }
        for leg in relevant
    ]
    return result[-max(1, int(limit)):][::-1]


def turn_table_v1(
    view: RhythmViewV1, *, threshold_pct: float, limit: int = 18,
) -> list[dict[str, object]]:
    events = view.turns.get(float(threshold_pct), ())
    return [
        {
            "Topp/bunn": "TOPP" if ev.kind == "PEAK" else "BUNN",
            "Topp-/bunntid": ev.pivot_at,
            "Bekreftet": ev.confirmed_at,
            "Deteksjonsforsinkelse min": round(
                (ev.confirmed_at - ev.pivot_at).total_seconds() / 60.0, 2
            ),
            "Pris": round(ev.price, 5),
        }
        for ev in events[-max(1, int(limit)):][::-1]
    ]


def amplitude_duration_counts_v1(
    view: RhythmViewV1,
) -> pd.DataFrame:
    """Heatmap rows are magnitude bins, columns are realized leg durations."""
    amplitude_labels = ("<0,1 %", "0,1–0,25 %", "0,25–0,5 %", "0,5–1 %", "1–3 %", ">=3 %")
    counts = pd.DataFrame(0, index=amplitude_labels, columns=DURATION_BUCKETS)
    # Use ONLY the smallest threshold to avoid counting one physical swing
    # six times (one occurrence per nested threshold).
    min_threshold = min(view.turns) if view.turns else None
    for leg in view.legs:
        if leg.threshold_pct != min_threshold:
            continue
        amplitude = leg.amplitude_pct
        bucket = (0 if amplitude < 0.1 else 1 if amplitude < 0.25
                  else 2 if amplitude < 0.5 else 3 if amplitude < 1
                  else 4 if amplitude < 3 else 5)
        counts.loc[amplitude_labels[bucket], duration_bucket_v1(leg.duration_minutes)] += 1
    return counts


def cross_scale_alignment_v1(view: RhythmViewV1) -> list[dict[str, object]]:
    """Retrospective nested-scale turn overlap; explicitly NOT a forecast."""
    thresholds = sorted(view.turns)
    output = []
    for small, large in zip(thresholds, thresholds[1:]):
        small_events = view.turns[small]
        large_events = view.turns[large]
        lags = []
        # Two-pointer chronological join: O(number of turns), not a nested
        # scan of every micro-pivot for each macro-pivot in the 7d dashboard.
        small_idx = 0
        most_recent: dict[tuple[int, str], ConfirmedTurnV1] = {}
        for big in large_events:
            while (small_idx < len(small_events)
                   and small_events[small_idx].confirmed_at <= big.confirmed_at):
                candidate = small_events[small_idx]
                most_recent[(candidate.segment, candidate.kind)] = candidate
                small_idx += 1
            earlier = most_recent.get((big.segment, big.kind))
            if earlier is not None:
                latency = (big.confirmed_at - earlier.confirmed_at).total_seconds() / 60
                lags.append(float(latency))
        output.append({
            "Mikroterskel %": small,
            "Makroterskel %": large,
            "Bekreftede makrovendinger": len(large_events),
            "Historisk match": len(lags),
            "Median bekreftelseslag min": round(median(lags), 2) if lags else None,
        })
    return output


@dataclass(frozen=True)
class EmpiricalFractalV1:
    """Completed macro-legs normalized by time and signed price displacement.

    Generated recursion is DESCRIPTIVE illustration, never a forecast.
    """
    x: tuple[float, ...]
    motif_y: tuple[float, ...]
    samples: tuple[tuple[float, ...], ...]
    median_dispersion: float
    sample_count: int


def empirical_fractal_motif_v1(
    view: RhythmViewV1, *, micro_threshold: float = 0.05,
    macro_threshold: float = 0.15, max_motifs: int = 12,
    grid_steps: int = 8,
) -> EmpiricalFractalV1 | None:
    """Learn a normalized repeating shape from real *completed* parent legs.

    One parent macro-leg needs >=2 finer turns inside it; ambiguous/flat
    macro-moves and turns confirmed after parent confirmation are excluded.
    This is not a predictive feature because historical macros are selected
    using their hindsight extremum locations.
    """
    import numpy as np

    if micro_threshold >= macro_threshold:
        raise ValueError("micro threshold must be below macro threshold")
    if grid_steps < 3 or grid_steps > 16:
        raise ValueError("grid_steps out of bounds")
    if max_motifs < 1 or max_motifs > 30:
        raise ValueError("max_motifs out of bounds")
    parents = view.turns.get(float(macro_threshold), ())
    children = view.turns.get(float(micro_threshold), ())
    if len(parents) < 2 or len(children) < 2:
        return None
    x = np.linspace(0.0, 1.0, grid_steps + 1)
    samples: list[tuple[float, ...]] = []
    for start, finish in zip(parents, parents[1:]):
        if start.segment != finish.segment or start.kind == finish.kind:
            continue
        duration = (finish.pivot_at - start.pivot_at).total_seconds()
        change = finish.price - start.price
        if duration <= 0 or abs(change) < 1e-12:
            continue
        eligible = [
            child for child in children
            if child.segment == start.segment
            and start.pivot_at < child.pivot_at < finish.pivot_at
            and child.confirmed_at <= finish.confirmed_at
        ]
        if len(eligible) < 2:
            continue
        xs = [0.0] + [
            (child.pivot_at - start.pivot_at).total_seconds() / duration
            for child in eligible
        ] + [1.0]
        ys = [0.0] + [
            (child.price - start.price) / change
            for child in eligible
        ] + [1.0]
        pairs = sorted(zip(xs, ys))
        unique_x: list[float] = []
        unique_y: list[float] = []
        for px, py in pairs:
            if unique_x and abs(px - unique_x[-1]) < 1e-12:
                continue
            unique_x.append(px)
            unique_y.append(py)
        samples.append(tuple(float(v) for v in np.interp(x, unique_x, unique_y)))
    if not samples:
        return None
    samples = samples[-max_motifs:]
    arr = np.asarray(samples, dtype=float)
    center = np.median(arr, axis=0)
    center[0], center[-1] = 0.0, 1.0
    dispersion = float(np.median(np.abs(arr - center[None, :])))
    return EmpiricalFractalV1(
        x=tuple(float(v) for v in x),
        motif_y=tuple(float(v) for v in center),
        samples=tuple(samples),
        median_dispersion=dispersion,
        sample_count=len(samples),
    )


def recursively_generated_fractal_v1(
    motif: EmpiricalFractalV1, *, depth: int = 3,
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Affine-replace segments with the empirical median market motif.

    Synthetic polyline stays in normalized [0,1] time; no claim that market
    will repeat the generated prices. Cap recursion to prevent UI overload.
    """
    if depth not in (1,2,3):
        raise ValueError("fractal depth must be 1..3")
    coords: list[tuple[float,float]] = [(0.0,0.0),(1.0,1.0)]
    for _ in range(depth):
        next_coords=[coords[0]]
        for (xa,ya),(xb,yb) in zip(coords,coords[1:]):
            for ux,uy in zip(motif.x[1:],motif.motif_y[1:]):
                next_coords.append((
                    xa + (xb-xa)*ux,
                    ya + (yb-ya)*uy,
                ))
        coords=next_coords
    return tuple(p[0] for p in coords), tuple(p[1] for p in coords)


__all__ = [
    "RhythmViewV1", "SwingLegV1", "DURATION_BUCKETS",
    "build_rhythm_view_v1", "duration_bucket_v1",
    "last_confirmed_legs_v1", "turn_table_v1",
    "amplitude_duration_counts_v1", "cross_scale_alignment_v1",
    "EmpiricalFractalV1", "empirical_fractal_motif_v1", "recursively_generated_fractal_v1",
]
