from __future__ import annotations

from datetime import datetime, timezone
from math import exp, log, sqrt
from statistics import fmean, pstdev
from typing import Any, Sequence

from spring_trade_engine.contracts import SpringObservationV1


def _utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _ewma(values: Sequence[float], span: int) -> float:
    if not values:
        raise ValueError("EWMA requires at least one value")
    alpha = 2.0 / (max(2, int(span)) + 1.0)
    result = float(values[0])
    for value in values[1:]:
        result = alpha * float(value) + (1.0 - alpha) * result
    return result


def _turning_state(velocities: Sequence[float], noise_floor: float) -> str:
    if not velocities:
        return "FLAT"
    current = float(velocities[-1])
    previous = float(velocities[-2]) if len(velocities) >= 2 else 0.0
    floor = max(1e-12, float(noise_floor) * 0.15)
    if abs(current) <= floor:
        return "FLAT"
    if previous < -floor and current > floor:
        return "TURN_UP"
    if previous > floor and current < -floor:
        return "TURN_DOWN"
    return "UP" if current > 0 else "DOWN"


def observe_bars_v1(
    bars: Sequence[Any],
    *,
    equilibrium_span: int = 20,
    minimum_bars: int = 12,
) -> SpringObservationV1:
    """Create one blind price-only Spring observation from canonical 1m bars.

    This is intentionally model-light. It records primitives that later oscillator,
    event and regime models can consume; it does not declare that a spring regime
    exists and has no trading side effects.
    """
    ordered = tuple(bars)
    if len(ordered) < max(4, int(minimum_bars)):
        raise ValueError("insufficient canonical bars for Spring observation")

    closes = [float(item.close) for item in ordered]
    highs = [float(item.high) for item in ordered]
    lows = [float(item.low) for item in ordered]
    if any(value <= 0 for value in closes):
        raise ValueError("Spring observation requires positive prices")

    log_returns = [log(closes[index] / closes[index - 1]) for index in range(1, len(closes))]
    return_mean = fmean(log_returns)
    return_sigma = pstdev(log_returns) if len(log_returns) >= 2 else 0.0
    safe_sigma = max(return_sigma, 1e-12)

    equilibrium = _ewma(closes, min(max(2, equilibrium_span), len(closes)))
    last_close = closes[-1]
    displacement_pct = ((last_close / equilibrium) - 1.0) * 100.0

    velocities = [value * 100.0 for value in log_returns]
    velocity = velocities[-1]
    previous_velocity = velocities[-2] if len(velocities) >= 2 else 0.0
    acceleration = velocity - previous_velocity

    realized_volatility_pct = return_sigma * 100.0
    ranges = [((high - low) / close) * 100.0 for high, low, close in zip(highs, lows, closes)]
    range_volatility_pct = fmean(ranges)
    shock_score = abs((log_returns[-1] - return_mean) / safe_sigma)

    equilibrium_sigma_pct = max(realized_volatility_pct * sqrt(max(1.0, equilibrium_span / 2.0)), 1e-9)
    displacement_z = displacement_pct / equilibrium_sigma_pct
    velocity_z = velocity / max(realized_volatility_pct, 1e-9)
    energy_proxy = 0.5 * (displacement_z * displacement_z + velocity_z * velocity_z)

    latest = ordered[-1]
    return SpringObservationV1(
        instrument_id=int(latest.instrument_id),
        market_id=int(latest.market_id),
        market_name=str(latest.market_name),
        observed_at=_utc(latest.bar_time),
        source_window_minutes=len(ordered),
        bar_count=len(ordered),
        close_price=last_close,
        equilibrium_price=equilibrium,
        displacement_pct=displacement_pct,
        velocity_pct_per_min=velocity,
        acceleration_pct_per_min2=acceleration,
        realized_volatility_pct=realized_volatility_pct,
        range_volatility_pct=range_volatility_pct,
        shock_score=shock_score,
        energy_proxy=energy_proxy,
        turning_state=_turning_state(velocities, realized_volatility_pct),
    )


__all__ = ["observe_bars_v1"]
