from __future__ import annotations

from dataclasses import dataclass
from math import sin, pi
from typing import Iterable

from forecast_contracts import ForecastSnapshot


@dataclass(frozen=True, slots=True)
class TrajectorySeries:
    history: tuple[tuple[float, float], ...]
    base: tuple[tuple[float, float], ...]
    bull: tuple[tuple[float, float], ...]
    bear: tuple[tuple[float, float], ...]
    fan_upper: tuple[tuple[float, float], ...]
    fan_lower: tuple[tuple[float, float], ...]
    profile: str


def _profile(forecast: ForecastSnapshot, *, market_regime: str = "", volatility_score: float | None = None) -> str:
    regime = market_regime.lower()
    volatility = 0.0 if volatility_score is None else float(volatility_score)
    if forecast.direction in {"NEUTRAL", "CONFLICTED", "INSUFFICIENT_DATA"} and volatility <= 0.2:
        return "SQUEEZE"
    if forecast.direction in {"NEUTRAL", "CONFLICTED", "INSUFFICIENT_DATA"}:
        return "RANGE"
    if "skiftende" in regime or "ustabilt" in regime:
        return "IMPULSE_REVERSAL"
    return "TREND"


def _shape(progress: float, endpoint: float, profile: str) -> float:
    p = max(0.0, min(1.0, progress))
    if profile == "SQUEEZE":
        return endpoint * (p ** 2.2)
    if profile == "RANGE":
        return endpoint * 0.35 * p + 0.12 * sin(3.0 * pi * p)
    if profile == "IMPULSE_REVERSAL":
        overshoot = endpoint * 1.45
        if p <= 0.45:
            return overshoot * (p / 0.45) ** 0.8
        return overshoot + (endpoint - overshoot) * ((p - 0.45) / 0.55)
    return endpoint * (0.15 * p + 0.85 * (3 * p * p - 2 * p * p * p))


def build_trajectory(
    forecast: ForecastSnapshot,
    *,
    history_prices: Iterable[tuple[str, float]] = (),
    market_regime: str = "",
    volatility_score: float | None = None,
    steps: int = 12,
) -> TrajectorySeries:
    ref = forecast.reference_price
    prices = [(stamp, float(price)) for stamp, price in history_prices if price is not None]
    if ref is None and prices:
        ref = prices[-1][1]
    ref = float(ref or 1.0)

    history: list[tuple[float, float]] = []
    if prices:
        count = max(1, len(prices) - 1)
        for index, (_, price) in enumerate(prices):
            x = 50.0 * index / count
            y = (price / ref - 1.0) * 100.0
            history.append((x, y))
    else:
        history.append((50.0, 0.0))

    low = float(forecast.expected_move_low_pct or 0.0)
    high = float(forecast.expected_move_high_pct or 0.0)
    base_end = (low + high) / 2.0
    profile = _profile(forecast, market_regime=market_regime, volatility_score=volatility_score)

    base: list[tuple[float, float]] = []
    bull: list[tuple[float, float]] = []
    bear: list[tuple[float, float]] = []
    upper: list[tuple[float, float]] = []
    lower: list[tuple[float, float]] = []
    for index in range(steps + 1):
        p = index / steps
        x = 50.0 + 50.0 * p
        base_y = _shape(p, base_end, profile)
        bull_y = _shape(p, high, profile)
        bear_y = _shape(p, low, profile)
        # Forecast uncertainty starts narrow at now and opens toward the supplied interval.
        fan = p ** 0.8
        upper_y = base_y + max(0.0, high - base_end) * fan
        lower_y = base_y - max(0.0, base_end - low) * fan
        base.append((x, base_y))
        bull.append((x, bull_y))
        bear.append((x, bear_y))
        upper.append((x, upper_y))
        lower.append((x, lower_y))

    return TrajectorySeries(
        history=tuple(history),
        base=tuple(base),
        bull=tuple(bull),
        bear=tuple(bear),
        fan_upper=tuple(upper),
        fan_lower=tuple(lower),
        profile=profile,
    )


def _polyline(points: tuple[tuple[float, float], ...], *, ymap) -> str:
    return " ".join(f"{x:.1f},{ymap(y):.1f}" for x, y in points)


def render_forecast_svg(
    forecast: ForecastSnapshot | None,
    *,
    history_prices: Iterable[tuple[str, float]] = (),
    market_regime: str = "",
    volatility_score: float | None = None,
    color: str = "#5a6b7b",
) -> str:
    if forecast is None:
        return '<div class="pg-forecast-empty">Ingen lagret prognose ennå.</div>'
    if forecast.horizon_hours is None or forecast.expected_move_low_pct is None or forecast.expected_move_high_pct is None:
        missing = ", ".join(forecast.missing_inputs) or "prognoseparametre"
        return f'<div class="pg-forecast-empty">Prognosen er foreløpig. Mangler: {missing}</div>'

    series = build_trajectory(
        forecast,
        history_prices=history_prices,
        market_regime=market_regime,
        volatility_score=volatility_score,
    )
    ys = [y for collection in (series.history, series.base, series.bull, series.bear, series.fan_upper, series.fan_lower) for _, y in collection]
    lower = min(ys + [-0.25])
    upper = max(ys + [0.25])
    span = max(0.5, upper - lower)
    pad = span * 0.18
    lower -= pad
    upper += pad

    def ymap(value: float) -> float:
        return 92.0 - (value - lower) / (upper - lower) * 76.0

    fan_points = list(series.fan_upper) + list(reversed(series.fan_lower))
    fan_polygon = _polyline(tuple(fan_points), ymap=ymap)
    zero_y = ymap(0.0)
    history = _polyline(series.history, ymap=ymap)
    base = _polyline(series.base, ymap=ymap)
    bull = _polyline(series.bull, ymap=ymap)
    bear = _polyline(series.bear, ymap=ymap)
    status = forecast.status
    missing = " · ".join(forecast.missing_inputs)
    horizon = f"{forecast.horizon_hours:g}t"
    interval = f"{forecast.expected_move_low_pct:+.2f}%…{forecast.expected_move_high_pct:+.2f}%"
    degradation = f" · mangler {missing}" if missing else ""

    return f'''<div class="pg-forecast-wrap">
      <div class="pg-forecast-head"><span>FORVENTET BANE</span><span>{series.profile.replace('_', ' ')}</span></div>
      <svg class="pg-forecast-svg" viewBox="0 0 100 108" preserveAspectRatio="none" role="img" aria-label="Historikk og prognose">
        <line x1="0" y1="{zero_y:.1f}" x2="100" y2="{zero_y:.1f}" class="pg-zero" />
        <line x1="50" y1="8" x2="50" y2="96" class="pg-now" />
        <polygon points="{fan_polygon}" class="pg-fan" />
        <polyline points="{history}" class="pg-history" />
        <polyline points="{bull}" class="pg-alt" />
        <polyline points="{bear}" class="pg-alt" />
        <polyline points="{base}" class="pg-base" style="stroke:{color}" />
        <text x="48" y="104" text-anchor="end" class="pg-axis-label">historikk</text>
        <text x="52" y="104" class="pg-axis-label">prognose</text>
      </svg>
      <div class="pg-forecast-meta"><strong>{interval}</strong> · {horizon} · {status}{degradation}</div>
    </div>'''
