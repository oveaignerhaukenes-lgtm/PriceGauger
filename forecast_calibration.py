from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Iterable

from forecast_learning import ForecastOutcome


CALIBRATION_ENGINE_VERSION = "forecast-calibration-v1"
DEFAULT_MIN_SAMPLES = 6
DEFAULT_RECENT_LIMIT = 40
MIN_APPLIED_FACTOR = 0.55
MAX_APPLIED_FACTOR = 1.80


@dataclass(frozen=True, slots=True)
class ForecastCalibration:
    market: str
    horizon_hours: float
    sample_count: int
    raw_factor: float
    applied_factor: float
    direction_hit_rate: float | None
    engine_version: str = CALIBRATION_ENGINE_VERSION


def _same_horizon(left: float | None, right: float, *, tolerance: float = 1e-6) -> bool:
    return left is not None and abs(float(left) - float(right)) <= tolerance


def _predicted_magnitude(outcome: ForecastOutcome) -> float | None:
    low = outcome.expected_move_low_pct
    high = outcome.expected_move_high_pct
    if low is None or high is None:
        return None
    magnitude = max(abs(float(low)), abs(float(high)))
    return magnitude if magnitude >= 0.01 else None


def build_forecast_calibration(
    outcomes: Iterable[ForecastOutcome],
    *,
    market: str,
    horizon_hours: float,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    recent_limit: int = DEFAULT_RECENT_LIMIT,
) -> ForecastCalibration | None:
    """Estimate a conservative recent movement-scale correction.

    Only COMPLETE outcomes for the same market and horizon participate. The raw
    correction is the median ratio between absolute realized movement and the
    forecast's outer expected movement. Individual ratios are clipped so one
    shock cannot dominate the profile, and the final correction is shrunk toward
    1.0 until the sample grows. Direction is deliberately not altered in v1.
    """

    usable: list[tuple[float, bool | None]] = []
    for outcome in outcomes:
        if outcome.market != market or outcome.status != "COMPLETE":
            continue
        if not _same_horizon(outcome.horizon_hours, horizon_hours):
            continue
        if outcome.realized_move_pct is None:
            continue
        predicted = _predicted_magnitude(outcome)
        if predicted is None:
            continue
        ratio = abs(float(outcome.realized_move_pct)) / predicted
        usable.append((max(0.25, min(4.0, ratio)), outcome.direction_hit))
        if len(usable) >= max(1, int(recent_limit)):
            break

    sample_count = len(usable)
    if sample_count < max(1, int(min_samples)):
        return None

    raw = float(median(item[0] for item in usable))
    # Recent data should matter, but calibration must not chase every short-lived
    # disturbance. Shrink toward neutral and asymptotically trust larger samples.
    trust = sample_count / (sample_count + 12.0)
    applied = 1.0 + (raw - 1.0) * trust
    applied = max(MIN_APPLIED_FACTOR, min(MAX_APPLIED_FACTOR, applied))

    directional = [bool(hit) for _, hit in usable if hit is not None]
    hit_rate = None if not directional else sum(directional) / len(directional)
    return ForecastCalibration(
        market=market,
        horizon_hours=float(horizon_hours),
        sample_count=sample_count,
        raw_factor=round(raw, 6),
        applied_factor=round(applied, 6),
        direction_hit_rate=None if hit_rate is None else round(hit_rate, 6),
    )
