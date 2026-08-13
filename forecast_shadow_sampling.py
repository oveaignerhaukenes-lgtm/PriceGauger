from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from forecast_contracts import ForecastSnapshot


DEFAULT_SHADOW_BUCKET_MINUTES = 6


def _as_utc(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def sample_forecast_shadows(
    forecasts: Iterable[ForecastSnapshot],
    *,
    bucket_minutes: int = DEFAULT_SHADOW_BUCKET_MINUTES,
) -> tuple[ForecastSnapshot, ...]:
    """Keep at most one historical forecast per bucket plus the active latest.

    Forecasts are expected in chronological order. The newest snapshot in each
    historical bucket is retained so the ghost trail follows the freshest thesis
    available at that point in time. The active latest forecast is always kept,
    even when it shares a bucket with the newest historical shadow.
    """
    ordered = tuple(forecasts)
    if len(ordered) <= 1:
        return ordered

    seconds = max(60, int(bucket_minutes) * 60)
    latest = ordered[-1]
    buckets: dict[int, ForecastSnapshot] = {}
    unparsed: list[ForecastSnapshot] = []
    for forecast in ordered[:-1]:
        stamp = _as_utc(forecast.as_of)
        if stamp is None:
            unparsed.append(forecast)
            continue
        bucket = int(stamp.timestamp()) // seconds
        buckets[bucket] = forecast

    sampled = [buckets[key] for key in sorted(buckets)]
    sampled.extend(unparsed)
    sampled.sort(key=lambda item: (_as_utc(item.as_of) or datetime.min.replace(tzinfo=timezone.utc), item.forecast_id))
    sampled.append(latest)
    return tuple(sampled)
