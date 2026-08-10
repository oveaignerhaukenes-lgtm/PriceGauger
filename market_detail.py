from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Sequence

from forecast_contracts import ForecastSnapshot
from forecast_visuals import build_trajectory


RESOLUTION_CHOICES = ("AUTO", "1m", "5m", "15m", "1t")


def _utc(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def resolution_minutes(choice: str, *, horizon_hours: float | None) -> int:
    normalized = str(choice or "AUTO").strip().upper()
    if normalized == "1M":
        return 1
    if normalized == "5M":
        return 5
    if normalized == "15M":
        return 15
    if normalized in {"1T", "1H"}:
        return 60
    horizon = float(horizon_hours or 4.0)
    if horizon <= 1.0:
        return 1
    if horizon <= 6.0:
        return 5
    if horizon <= 24.0:
        return 15
    return 60


def downsample_history(
    points: Iterable[tuple[str, float]],
    *,
    minutes: int,
) -> tuple[tuple[str, float], ...]:
    bucket_seconds = max(60, int(minutes) * 60)
    buckets: dict[int, tuple[datetime, float]] = {}
    for stamp, price in points:
        observed = _utc(stamp)
        key = int(observed.timestamp()) // bucket_seconds
        buckets[key] = (observed, float(price))
    ordered = [buckets[key] for key in sorted(buckets)]
    return tuple((stamp.isoformat(), price) for stamp, price in ordered)


def ghost_forecast_opacities(count: int, *, minimum: float = 0.08, maximum: float = 0.34) -> tuple[float, ...]:
    """Return oldest-to-newest opacity levels for historical forecast trails."""
    total = max(0, int(count))
    if total == 0:
        return ()
    if total == 1:
        return (float(maximum),)
    low = float(minimum)
    high = float(maximum)
    step = (high - low) / (total - 1)
    return tuple(low + step * index for index in range(total))


def fade_path_segments(
    points: Sequence[tuple[datetime, float]],
    *,
    peak_opacity: float,
    minimum_ratio: float = 0.18,
) -> tuple[tuple[tuple[tuple[datetime, float], ...], float], ...]:
    """Split a path into pairwise segments that fade from left to right.

    Plotly line traces do not support per-vertex opacity. Pairwise segments let
    Markedsvisning reproduce the forecast-card trail effect without altering the
    underlying forecast trajectory.
    """
    if len(points) < 2:
        return ()
    peak = max(0.0, min(1.0, float(peak_opacity)))
    floor = peak * max(0.0, min(1.0, float(minimum_ratio)))
    segment_count = len(points) - 1
    result: list[tuple[tuple[tuple[datetime, float], ...], float]] = []
    for index in range(segment_count):
        progress = (index + 1) / segment_count
        opacity = floor + (peak - floor) * (progress ** 1.35)
        result.append(((points[index], points[index + 1]), opacity))
    return tuple(result)


@dataclass(frozen=True, slots=True)
class ForecastPriceSeries:
    base: tuple[tuple[str, float], ...]
    bull: tuple[tuple[str, float], ...]
    bear: tuple[tuple[str, float], ...]
    fan_upper: tuple[tuple[str, float], ...]
    fan_lower: tuple[tuple[str, float], ...]


def forecast_price_series(
    forecast: ForecastSnapshot,
    *,
    market_regime: str = "",
    volatility_score: float | None = None,
    steps: int = 24,
) -> ForecastPriceSeries:
    if forecast.reference_price is None or forecast.horizon_hours is None:
        return ForecastPriceSeries((), (), (), (), ())
    if forecast.expected_move_low_pct is None or forecast.expected_move_high_pct is None:
        return ForecastPriceSeries((), (), (), (), ())

    trajectory = build_trajectory(
        forecast,
        market_regime=market_regime,
        volatility_score=volatility_score,
        steps=steps,
    )
    start = _utc(forecast.as_of)
    horizon = float(forecast.horizon_hours)
    reference = float(forecast.reference_price)

    def convert(points: tuple[tuple[float, float], ...]) -> tuple[tuple[str, float], ...]:
        converted: list[tuple[str, float]] = []
        for x, move_pct in points:
            progress = max(0.0, min(1.0, (float(x) - 50.0) / 50.0))
            stamp = start + timedelta(hours=horizon * progress)
            price = reference * (1.0 + float(move_pct) / 100.0)
            converted.append((stamp.isoformat(), price))
        return tuple(converted)

    return ForecastPriceSeries(
        base=convert(trajectory.base),
        bull=convert(trajectory.bull),
        bear=convert(trajectory.bear),
        fan_upper=convert(trajectory.fan_upper),
        fan_lower=convert(trajectory.fan_lower),
    )
