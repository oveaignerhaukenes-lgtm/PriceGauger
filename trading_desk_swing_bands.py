from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from collections.abc import Sequence

from trading_desk import ChartBar


@dataclass(frozen=True, slots=True)
class SwingBand:
    kind: str
    pivot_price: float
    lower: float
    upper: float
    pivot_time: object


def _true_ranges(bars: Sequence[ChartBar]) -> list[float]:
    result: list[float] = []
    for index, bar in enumerate(bars):
        high = float(bar.high)
        low = float(bar.low)
        if index == 0:
            result.append(max(0.0, high - low))
            continue
        previous_close = float(bars[index - 1].close)
        result.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    return result


def derive_swing_bands(
    bars: Sequence[ChartBar],
    *,
    pivot_radius: int = 2,
    lookback_bars: int = 180,
) -> tuple[SwingBand, ...]:
    """Return nearest confirmed swing-low/high zones around the current price.

    Pivots require bars on both sides, so the latest unconfirmed edge can never
    become a swing level. Band width comes from recent true range and is only a
    visualization of the observed zone, not a trading instruction.
    """
    if pivot_radius < 1:
        raise ValueError("pivot_radius must be positive")
    if len(bars) < 2 * pivot_radius + 1:
        return ()

    sample = tuple(bars[-max(2 * pivot_radius + 1, int(lookback_bars)):])
    highs: list[tuple[float, object]] = []
    lows: list[tuple[float, object]] = []
    for index in range(pivot_radius, len(sample) - pivot_radius):
        item = sample[index]
        left = sample[index - pivot_radius:index]
        right = sample[index + 1:index + pivot_radius + 1]
        high = float(item.high)
        low = float(item.low)
        if all(high >= float(other.high) for other in (*left, *right)):
            highs.append((high, item.bar_time))
        if all(low <= float(other.low) for other in (*left, *right)):
            lows.append((low, item.bar_time))

    if not highs and not lows:
        return ()

    current = float(sample[-1].close)
    recent_ranges = [value for value in _true_ranges(sample)[-20:] if value > 0.0]
    typical_range = median(recent_ranges) if recent_ranges else abs(current) * 0.001
    half_width = max(float(typical_range) * 0.22, abs(current) * 0.0002, 1e-9)

    selected: list[SwingBand] = []
    if lows:
        candidates = [item for item in lows if item[0] <= current]
        pivot = max(candidates, key=lambda item: item[0]) if candidates else lows[-1]
        selected.append(
            SwingBand("LOW", pivot[0], pivot[0] - half_width, pivot[0] + half_width, pivot[1])
        )
    if highs:
        candidates = [item for item in highs if item[0] >= current]
        pivot = min(candidates, key=lambda item: item[0]) if candidates else highs[-1]
        selected.append(
            SwingBand("HIGH", pivot[0], pivot[0] - half_width, pivot[0] + half_width, pivot[1])
        )
    return tuple(selected)


def add_swing_bands_to_figure(fig, bars: Sequence[ChartBar]) -> tuple[SwingBand, ...]:
    bands = derive_swing_bands(bars)
    for band in bands:
        is_low = band.kind == "LOW"
        # Keep structural zones visible without competing with price/forecast data.
        fill = "rgba(22,163,74,0.045)" if is_low else "rgba(220,38,38,0.040)"
        line = "rgba(22,163,74,0.20)" if is_low else "rgba(220,38,38,0.18)"
        annotation = "rgba(22,163,74,0.62)" if is_low else "rgba(220,38,38,0.60)"
        label = "Swing low" if is_low else "Swing high"
        fig.add_hrect(
            y0=band.lower,
            y1=band.upper,
            fillcolor=fill,
            line={"color": line, "width": 0.6},
            annotation_text=f"{label} · {band.pivot_price:g}",
            annotation_position="right",
            annotation_font={"color": annotation, "size": 10},
            row=1,
            col=1,
        )
    return bands
