from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import ceil, floor, log10, pi, sin
from typing import Iterable

from forecast_contracts import ForecastSnapshot
from forecast_visuals import MISSING_INPUT_LABELS


@dataclass(frozen=True, slots=True)
class TimelineForecast:
    snapshot: ForecastSnapshot
    as_of: datetime
    ends_at: datetime


@dataclass(frozen=True, slots=True)
class TimelineGap:
    start: datetime
    end: datetime
    label: str


def _as_utc(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _profile(
    forecast: ForecastSnapshot,
    *,
    market_regime: str = "",
    volatility_score: float | None = None,
) -> str:
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


def _eligible(snapshot: ForecastSnapshot) -> TimelineForecast | None:
    if (
        snapshot.reference_price is None
        or snapshot.horizon_hours is None
        or snapshot.expected_move_low_pct is None
        or snapshot.expected_move_high_pct is None
    ):
        return None
    as_of = _as_utc(snapshot.as_of)
    if as_of is None:
        return None
    horizon = max(0.25, float(snapshot.horizon_hours))
    return TimelineForecast(
        snapshot=snapshot,
        as_of=as_of,
        ends_at=as_of + timedelta(hours=horizon),
    )


def _points(points: Iterable[tuple[float, float]], *, ymap) -> str:
    return " ".join(f"{x:.1f},{ymap(y):.1f}" for x, y in points)


def _missing_text(snapshot: ForecastSnapshot) -> str:
    return " · ".join(
        MISSING_INPUT_LABELS.get(str(item), str(item).replace("_", " "))
        for item in snapshot.missing_inputs
    )


def _crosses_weekend(start: datetime, end: datetime) -> bool:
    day = start.date()
    last = end.date()
    while day <= last:
        if day.weekday() >= 5:
            return True
        day += timedelta(days=1)
    return False


def _timeline_gaps(
    observed: Iterable[tuple[datetime, float]],
    *,
    threshold: timedelta = timedelta(hours=6),
) -> tuple[TimelineGap, ...]:
    points = tuple(observed)
    gaps: list[TimelineGap] = []
    for (previous_time, _), (current_time, _) in zip(points, points[1:]):
        if current_time - previous_time <= threshold:
            continue
        label = "WEEKEND GAP" if _crosses_weekend(previous_time, current_time) else "MARKET GAP"
        gaps.append(TimelineGap(previous_time, current_time, label))
    return tuple(gaps)


def _display_seconds(
    stamp: datetime,
    *,
    axis_start: datetime,
    gaps: Iterable[TimelineGap],
    compressed_gap: timedelta = timedelta(minutes=15),
) -> float:
    cursor = axis_start
    displayed = 0.0
    compressed_seconds = max(1.0, compressed_gap.total_seconds())
    for gap in gaps:
        if gap.end <= axis_start:
            continue
        gap_start = max(axis_start, gap.start)
        if stamp <= gap_start:
            return displayed + max(0.0, (stamp - cursor).total_seconds())
        displayed += max(0.0, (gap_start - cursor).total_seconds())
        gap_duration = max(1.0, (gap.end - gap_start).total_seconds())
        if stamp <= gap.end:
            progress = max(0.0, min(1.0, (stamp - gap_start).total_seconds() / gap_duration))
            return displayed + compressed_seconds * progress
        displayed += compressed_seconds
        cursor = gap.end
    return displayed + max(0.0, (stamp - cursor).total_seconds())


def _observed_segments(
    observed: Iterable[tuple[datetime, float]],
    *,
    gap_threshold: timedelta = timedelta(hours=6),
) -> tuple[tuple[tuple[datetime, float], ...], ...]:
    points = tuple(observed)
    if not points:
        return ()
    segments: list[list[tuple[datetime, float]]] = [[points[0]]]
    for point in points[1:]:
        if point[0] - segments[-1][-1][0] > gap_threshold:
            segments.append([point])
        else:
            segments[-1].append(point)
    return tuple(tuple(segment) for segment in segments)


def _nice_tick_step(lower: float, upper: float, *, target_ticks: int = 4) -> float:
    span = max(0.01, float(upper) - float(lower))
    raw = max(1.0, span / max(2, int(target_ticks)))
    magnitude = 10.0 ** floor(log10(raw))
    normalized = raw / magnitude
    if normalized <= 1.0:
        nice = 1.0
    elif normalized <= 2.0:
        nice = 2.0
    elif normalized <= 5.0:
        nice = 5.0
    else:
        nice = 10.0
    return max(1.0, nice * magnitude)


def _price_ticks(lower: float, upper: float) -> tuple[float, ...]:
    step = _nice_tick_step(lower, upper)
    first = ceil(lower / step) * step
    last = floor(upper / step) * step
    if first > last:
        midpoint = round((lower + upper) / 2.0)
        return (float(midpoint),)
    ticks: list[float] = []
    value = first
    while value <= last + step * 0.001 and len(ticks) < 8:
        ticks.append(float(value))
        value += step
    return tuple(ticks)


def render_forecast_timeline_svg(
    forecasts: Iterable[ForecastSnapshot],
    *,
    observed_prices: Iterable[tuple[str, float]] = (),
    market_regime: str = "",
    volatility_score: float | None = None,
    color: str = "#5a6b7b",
    now: datetime | None = None,
    max_layers: int = 4,
    steps: int = 12,
) -> str:
    """Render immutable forecast snapshots against one canonical observed price timeline."""

    candidates = [item for item in (_eligible(snapshot) for snapshot in forecasts) if item is not None]
    candidates.sort(key=lambda item: item.as_of)
    layers = candidates[-max(1, int(max_layers)) :]
    if not layers:
        return '<div class="pg-forecast-empty">Ingen komplett lagret prognose ennå.</div>'

    observed: list[tuple[datetime, float]] = []
    for stamp, price in observed_prices:
        parsed = _as_utc(stamp)
        if parsed is not None and price is not None:
            observed.append((parsed, float(price)))
    observed.sort(key=lambda item: item[0])

    earliest_forecast = layers[0].as_of
    latest_forecast = layers[-1]
    axis_start = observed[0][0] if observed and observed[0][0] < earliest_forecast else earliest_forecast
    axis_end = max(item.ends_at for item in layers)
    if observed and observed[-1][0] > axis_end:
        axis_end = observed[-1][0]
    gaps = _timeline_gaps(observed)
    display_span = max(
        1.0,
        _display_seconds(axis_end, axis_start=axis_start, gaps=gaps),
    )
    plot_right = 90.0

    def xmap(stamp: datetime) -> float:
        displayed = _display_seconds(stamp, axis_start=axis_start, gaps=gaps)
        return max(0.0, min(plot_right, displayed / display_span * plot_right))

    plotted_layers: list[dict[str, object]] = []
    all_prices: list[float] = [price for _, price in observed]
    for index, item in enumerate(layers):
        snapshot = item.snapshot
        ref = float(snapshot.reference_price)
        low = float(snapshot.expected_move_low_pct)
        high = float(snapshot.expected_move_high_pct)
        base_end = (low + high) / 2.0
        profile = _profile(snapshot, market_regime=market_regime, volatility_score=volatility_score)
        base: list[tuple[float, float]] = []
        bull: list[tuple[float, float]] = []
        bear: list[tuple[float, float]] = []
        upper: list[tuple[float, float]] = []
        lower: list[tuple[float, float]] = []
        for step in range(max(2, int(steps)) + 1):
            progress = step / max(2, int(steps))
            stamp = item.as_of + (item.ends_at - item.as_of) * progress
            x = xmap(stamp)
            base_move = _shape(progress, base_end, profile)
            bull_move = _shape(progress, high, profile)
            bear_move = _shape(progress, low, profile)
            fan = progress ** 0.8
            upper_move = base_move + max(0.0, high - base_end) * fan
            lower_move = base_move - max(0.0, base_end - low) * fan
            base_price = ref * (1.0 + base_move / 100.0)
            bull_price = ref * (1.0 + bull_move / 100.0)
            bear_price = ref * (1.0 + bear_move / 100.0)
            upper_price = ref * (1.0 + upper_move / 100.0)
            lower_price = ref * (1.0 + lower_move / 100.0)
            base.append((x, base_price))
            bull.append((x, bull_price))
            bear.append((x, bear_price))
            upper.append((x, upper_price))
            lower.append((x, lower_price))
            all_prices.extend((base_price, bull_price, bear_price, upper_price, lower_price))
        plotted_layers.append(
            {
                "item": item,
                "index": index,
                "base": tuple(base),
                "bull": tuple(bull),
                "bear": tuple(bear),
                "upper": tuple(upper),
                "lower": tuple(lower),
            }
        )

    if not all_prices:
        all_prices = [1.0]
    lower_price = min(all_prices)
    upper_price = max(all_prices)
    price_span = max(abs(upper_price) * 0.001, upper_price - lower_price, 0.01)
    pad = price_span * 0.10
    lower_price -= pad
    upper_price += pad

    def ymap(value: float) -> float:
        return 92.0 - (value - lower_price) / (upper_price - lower_price) * 80.0

    grid_markup: list[str] = []
    for tick in _price_ticks(lower_price, upper_price):
        y = ymap(tick)
        grid_markup.append(
            f'<line x1="0" y1="{y:.1f}" x2="{plot_right:.1f}" y2="{y:.1f}" '
            'style="stroke:rgba(100,116,139,.14);stroke-width:.45;vector-effect:non-scaling-stroke" />'
        )
        grid_markup.append(
            f'<text x="92.0" y="{y + 1.5:.1f}" '
            'style="font-size:4.5px;fill:rgba(71,85,105,.76);font-family:system-ui,sans-serif">'
            f'{tick:.0f}</text>'
        )
    grid_markup.append(
        '<line x1="90" y1="10" x2="90" y2="94" '
        'style="stroke:rgba(100,116,139,.25);stroke-width:.5;vector-effect:non-scaling-stroke" />'
    )

    gap_markup: list[str] = []
    for gap in gaps:
        if gap.end < axis_start or gap.start > axis_end:
            continue
        left = xmap(max(axis_start, gap.start))
        right = xmap(min(axis_end, gap.end))
        width = max(1.6, right - left)
        center = min(plot_right - width / 2.0, left + width / 2.0)
        gap_markup.append(
            f'<rect x="{center - width / 2.0:.1f}" y="8" width="{width:.1f}" height="88" rx=".8" '
            'style="fill:rgba(100,116,139,.10);stroke:rgba(100,116,139,.38);stroke-width:.45;'
            'stroke-dasharray:1.2 1.2;vector-effect:non-scaling-stroke" />'
        )
        gap_markup.append(
            f'<text x="{center:.1f}" y="14" text-anchor="middle" '
            'style="font-size:2.7px;font-weight:700;letter-spacing:.08em;fill:rgba(71,85,105,.78);'
            'font-family:system-ui,sans-serif">'
            f'{gap.label}</text>'
        )

    layer_markup: list[str] = []
    count = len(plotted_layers)
    fan_opacities = (0.08, 0.11, 0.16, 0.24)
    line_opacities = (0.28, 0.42, 0.62, 0.95)
    for ordinal, layer in enumerate(plotted_layers):
        upper = layer["upper"]
        lower = layer["lower"]
        base = layer["base"]
        fan_polygon = _points(tuple(upper) + tuple(reversed(lower)), ymap=ymap)
        fan_opacity = fan_opacities[min(ordinal + (4 - count), len(fan_opacities) - 1)]
        line_opacity = line_opacities[min(ordinal + (4 - count), len(line_opacities) - 1)]
        item = layer["item"]
        start_x = xmap(item.as_of)
        layer_markup.append(
            f'<line x1="{start_x:.1f}" y1="8" x2="{start_x:.1f}" y2="96" '
            f'style="stroke:{color};stroke-width:.45;stroke-opacity:{line_opacity:.2f};stroke-dasharray:1.5 2;vector-effect:non-scaling-stroke" />'
        )
        layer_markup.append(
            f'<polygon points="{fan_polygon}" class="pg-forecast-layer pg-forecast-fan" '
            f'style="fill:{color};fill-opacity:{fan_opacity:.2f};stroke:none" />'
        )
        layer_markup.append(
            f'<polyline points="{_points(base, ymap=ymap)}" class="pg-forecast-layer pg-forecast-base" '
            f'style="fill:none;stroke:{color};stroke-width:{1.15 if ordinal < count - 1 else 2.0};'
            f'stroke-opacity:{line_opacity:.2f};vector-effect:non-scaling-stroke" />'
        )

    latest = plotted_layers[-1]
    layer_markup.append(
        f'<polyline points="{_points(latest["bull"], ymap=ymap)}" class="pg-alt pg-bull" '
        'style="fill:none;stroke:#2f9e64;stroke-width:1.0;stroke-dasharray:2 1.4;vector-effect:non-scaling-stroke" />'
    )
    layer_markup.append(
        f'<polyline points="{_points(latest["bear"], ymap=ymap)}" class="pg-alt pg-bear" '
        'style="fill:none;stroke:#d15b5b;stroke-width:1.0;stroke-dasharray:2 1.4;vector-effect:non-scaling-stroke" />'
    )

    observed_in_axis = [(stamp, price) for stamp, price in observed if axis_start <= stamp <= axis_end]
    actual_markup = ""
    if observed_in_axis:
        actual_parts: list[str] = []
        for segment in _observed_segments(observed_in_axis):
            segment_points = [(xmap(stamp), price) for stamp, price in segment]
            if len(segment_points) >= 2:
                actual_parts.append(
                    f'<polyline points="{_points(segment_points, ymap=ymap)}" class="pg-realized" '
                    'style="fill:none;stroke:#111827;stroke-width:1.8;vector-effect:non-scaling-stroke" />'
                )
            elif segment_points:
                x, price = segment_points[0]
                actual_parts.append(
                    f'<circle cx="{x:.1f}" cy="{ymap(price):.1f}" r=".85" '
                    'style="fill:#111827;stroke:none" />'
                )
        last_stamp, last_price = observed_in_axis[-1]
        last_x = xmap(last_stamp)
        actual_parts.append(
            f'<circle cx="{last_x:.1f}" cy="{ymap(last_price):.1f}" r="1.35" '
            'style="fill:#111827;stroke:white;stroke-width:.45;vector-effect:non-scaling-stroke" />'
        )
        actual_markup = "".join(actual_parts)

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    now_markup = ""
    if axis_start <= current <= axis_end:
        now_x = xmap(current)
        now_markup = (
            f'<line x1="{now_x:.1f}" y1="8" x2="{now_x:.1f}" y2="96" class="pg-now" '
            'style="stroke:#64748b;stroke-width:.8;stroke-dasharray:2 1.5;vector-effect:non-scaling-stroke" />'
        )

    latest_snapshot = latest_forecast.snapshot
    interval = f"{latest_snapshot.expected_move_low_pct:+.2f}%…{latest_snapshot.expected_move_high_pct:+.2f}%"
    horizon = f"{latest_snapshot.horizon_hours:g}t"
    missing = _missing_text(latest_snapshot)
    degradation = f" · {missing}" if missing else ""
    actual_label = "faktisk pris oppdateres fra canonical 1m-bars" if observed_in_axis else "venter på faktisk pris"

    return f'''<div class="pg-forecast-wrap" style="overflow:hidden">
      <div class="pg-forecast-head"><span>PROGNOSE VS. VIRKELIGHET</span><span>{len(layers)} SNAPSHOT{'S' if len(layers) != 1 else ''}</span></div>
      <svg class="pg-forecast-svg" style="height:13.5rem" viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="Flere lagrede prognoser mot faktisk markedsutvikling med prisakse til høyre">
        {''.join(grid_markup)}
        {''.join(gap_markup)}
        {''.join(layer_markup)}
        {actual_markup}
        {now_markup}
      </svg>
      <div style="display:flex;justify-content:space-between;gap:.5rem;font-size:.58rem;opacity:.62;margin-top:-.2rem">
        <span>eldre prognoser lysere · nyeste tydeligst</span><span>svart = faktisk pris · høyre = pris</span>
      </div>
      <div class="pg-forecast-meta"><strong>{interval}</strong> · {horizon} · {latest_snapshot.status}{degradation} · {actual_label}</div>
    </div>'''
