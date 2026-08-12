from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import ceil, floor, log10
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
    """Choose only shapes justified by the persisted evidence.

    V1 used decorative squeeze/range/S-curves even when the snapshot only knew an
    endpoint interval. The default is now conservative linear state continuation.
    A reversal profile is retained only for a strong READY forecast in an
    explicitly unstable regime; otherwise the renderer does not invent a knee.
    """

    regime = market_regime.lower()
    if (
        forecast.status == "READY"
        and float(forecast.confidence) >= 0.70
        and forecast.direction in {"LONG_BIAS", "SHORT_BIAS"}
        and ("skiftende" in regime or "ustabilt" in regime)
    ):
        return "IMPULSE_REVERSAL"
    return "TREND"


def _shape(progress: float, endpoint: float, profile: str) -> float:
    p = max(0.0, min(1.0, progress))
    if profile == "IMPULSE_REVERSAL":
        overshoot = endpoint * 1.25
        if p <= 0.45:
            return overshoot * (p / 0.45)
        return overshoot + (endpoint - overshoot) * ((p - 0.45) / 0.55)
    return endpoint * p


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


def _is_weekend_closure_gap(start: datetime, end: datetime) -> bool:
    """Return true only for a gap that plausibly bridges the market weekend."""

    duration = end - start
    if duration < timedelta(hours=24):
        return False
    if start.weekday() >= 5:
        return False
    return end.weekday() in {6, 0}


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
        label = "WEEKEND GAP" if _is_weekend_closure_gap(previous_time, current_time) else "MARKET GAP"
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


def _layer_opacity(ordinal: int, count: int) -> tuple[float, float]:
    """Fade every visible immutable snapshot while preserving a useful floor."""
    if count <= 1:
        return 0.24, 0.95
    progress = max(0.0, min(1.0, ordinal / (count - 1)))
    fan = 0.035 + 0.205 * (progress ** 1.35)
    line = 0.12 + 0.83 * (progress ** 1.15)
    return fan, line


def _visible_window(
    candidates: tuple[TimelineForecast, ...],
    observed: tuple[tuple[datetime, float], ...],
) -> tuple[datetime, datetime]:
    """Use a rolling, count-independent viewport tied to the latest horizon.

    Two horizons are shown: roughly one horizon of history and one horizon of
    forecast/realization. Old forecast layers remain until their own end point has
    physically crossed the left boundary.
    """

    latest = candidates[-1]
    horizon = max(timedelta(minutes=15), latest.ends_at - latest.as_of)
    axis_end = latest.ends_at
    if observed:
        axis_end = max(axis_end, observed[-1][0])
    return axis_end - 2 * horizon, axis_end


def render_forecast_timeline_svg(
    forecasts: Iterable[ForecastSnapshot],
    *,
    observed_prices: Iterable[tuple[str, float]] = (),
    market_regime: str = "",
    volatility_score: float | None = None,
    color: str = "#5a6b7b",
    now: datetime | None = None,
    max_layers: int | None = None,
    steps: int = 12,
) -> str:
    """Render immutable forecast snapshots against one canonical observed price timeline."""

    candidates = tuple(
        sorted(
            (item for item in (_eligible(snapshot) for snapshot in forecasts) if item is not None),
            key=lambda item: (item.as_of, item.snapshot.forecast_id),
        )
    )
    if not candidates:
        return '<div class="pg-forecast-empty">Ingen komplett lagret prognose ennå.</div>'

    observed_list: list[tuple[datetime, float]] = []
    for stamp, price in observed_prices:
        parsed = _as_utc(stamp)
        if parsed is not None and price is not None:
            observed_list.append((parsed, float(price)))
    observed_list.sort(key=lambda item: item[0])
    observed = tuple(observed_list)

    axis_start, axis_end = _visible_window(candidates, observed)
    layers = [item for item in candidates if item.ends_at >= axis_start and item.as_of <= axis_end]
    if max_layers is not None:
        layers = layers[-max(1, int(max_layers)) :]

    observed_in_window = tuple(item for item in observed if axis_start <= item[0] <= axis_end)
    gaps = _timeline_gaps(observed_in_window)
    display_span = max(1.0, _display_seconds(axis_end, axis_start=axis_start, gaps=gaps))
    plot_right = 90.0

    def xmap(stamp: datetime) -> float:
        displayed = _display_seconds(stamp, axis_start=axis_start, gaps=gaps)
        return max(0.0, min(plot_right, displayed / display_span * plot_right))

    plotted_layers: list[dict[str, object]] = []
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
        low_evidence = snapshot.status != "READY" or float(snapshot.confidence) < 0.55
        fan_exponent = 0.45 if low_evidence else 0.8
        for step in range(max(2, int(steps)) + 1):
            progress = step / max(2, int(steps))
            stamp = item.as_of + (item.ends_at - item.as_of) * progress
            x = xmap(stamp)
            base_move = _shape(progress, base_end, profile)
            bull_move = _shape(progress, high, profile)
            bear_move = _shape(progress, low, profile)
            fan = progress ** fan_exponent
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

    scale_start = axis_start
    if gaps:
        scale_start = gaps[-1].end
    scale_observed = [price for stamp, price in observed_in_window if scale_start <= stamp <= axis_end]
    latest_forecast = candidates[-1]
    latest_forecast_prices: list[float] = []
    if plotted_layers:
        latest_layer = plotted_layers[-1]
        latest_forecast_prices = [
            price
            for key in ("base", "bull", "bear", "upper", "lower")
            for _, price in latest_layer[key]
        ]
    scale_prices = scale_observed + latest_forecast_prices
    if not scale_prices:
        scale_prices = [float(latest_forecast.snapshot.reference_price)]
    lower_price = min(scale_prices)
    upper_price = max(scale_prices)
    price_span = max(abs(upper_price) * 0.001, upper_price - lower_price, 0.01)
    pad = price_span * 0.10
    lower_price -= pad
    upper_price += pad

    def ymap(value: float) -> float:
        return 92.0 - (value - lower_price) / (upper_price - lower_price) * 80.0

    grid_markup: list[str] = []
    axis_labels: list[str] = []
    for tick in _price_ticks(lower_price, upper_price):
        y = ymap(tick)
        grid_markup.append(
            f'<line x1="0" y1="{y:.1f}" x2="{plot_right:.1f}" y2="{y:.1f}" '
            'style="stroke:rgba(100,116,139,.14);stroke-width:.45;vector-effect:non-scaling-stroke" />'
        )
        axis_labels.append(
            f'<span style="position:absolute;right:.12rem;top:{y:.1f}%;transform:translateY(-50%);'
            'font-size:.64rem;font-weight:400;line-height:1;color:inherit;opacity:.82;white-space:nowrap">'
            f'{tick:g}</span>'
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
            f'<rect x="{center - width / 2.0:.1f}" y="14" width="{width:.1f}" height="82" rx=".8" '
            'style="fill:rgba(100,116,139,.10);stroke:rgba(100,116,139,.38);stroke-width:.45;'
            'stroke-dasharray:1.2 1.2;vector-effect:non-scaling-stroke">'
            f'<title>{gap.label}</title></rect>'
        )
        if width >= 7.0:
            label_parts = gap.label.split(maxsplit=1)
            label_top = label_parts[0]
            label_bottom = label_parts[1] if len(label_parts) > 1 else ""
            gap_markup.append(
                f'<text x="{center:.1f}" y="9.2" text-anchor="middle" '
                'style="font-size:1.8px;font-weight:400;letter-spacing:0;fill:rgba(71,85,105,.78);'
                'font-family:system-ui,sans-serif">'
                f'<tspan x="{center:.1f}" dy="0">{label_top}</tspan>'
                f'<tspan x="{center:.1f}" dy="1.7">{label_bottom}</tspan>'
                '</text>'
            )

    layer_markup: list[str] = []
    count = len(plotted_layers)
    for ordinal, layer in enumerate(plotted_layers):
        upper = layer["upper"]
        lower = layer["lower"]
        base = layer["base"]
        fan_polygon = _points(tuple(upper) + tuple(reversed(lower)), ymap=ymap)
        fan_opacity, line_opacity = _layer_opacity(ordinal, count)
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

    if plotted_layers:
        latest = plotted_layers[-1]
        layer_markup.append(
            f'<polyline points="{_points(latest["bull"], ymap=ymap)}" class="pg-alt pg-bull" '
            'style="fill:none;stroke:#2f9e64;stroke-width:1.0;stroke-dasharray:2 1.4;vector-effect:non-scaling-stroke" />'
        )
        layer_markup.append(
            f'<polyline points="{_points(latest["bear"], ymap=ymap)}" class="pg-alt pg-bear" '
            'style="fill:none;stroke:#d15b5b;stroke-width:1.0;stroke-dasharray:2 1.4;vector-effect:non-scaling-stroke" />'
        )

    actual_markup = ""
    if observed_in_window:
        actual_parts: list[str] = []
        for segment in _observed_segments(observed_in_window):
            segment_points = [(xmap(stamp), price) for stamp, price in segment]
            if len(segment_points) >= 2:
                actual_parts.append(
                    f'<polyline points="{_points(segment_points, ymap=ymap)}" class="pg-realized" '
                    'style="fill:none;stroke:currentColor;stroke-width:1.9;vector-effect:non-scaling-stroke" />'
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
    actual_label = "faktisk pris oppdateres fra canonical 1m-bars" if observed_in_window else "venter på faktisk pris"

    fragment = f'''<div class="pg-forecast-wrap" style="overflow:hidden">
      <div class="pg-forecast-head"><span>PROGNOSE VS. VIRKELIGHET</span><span>{len(layers)} SYNLIGE</span></div>
      <div class="pg-forecast-plot" style="position:relative;height:13.5rem">
        <svg class="pg-forecast-svg" style="height:13.5rem;display:block" viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="Lagrede prognoser mot faktisk markedsutvikling med prisakse til høyre">
          {''.join(grid_markup)}
          {''.join(gap_markup)}
          {''.join(layer_markup)}
          {actual_markup}
          {now_markup}
        </svg>
        <div class="pg-price-axis" aria-hidden="true" style="position:absolute;inset:0;pointer-events:none">{''.join(axis_labels)}</div>
      </div>
      <div style="display:flex;justify-content:space-between;gap:.5rem;font-size:.58rem;opacity:.72;margin-top:.08rem">
        <span>eldre prognoser lysere · beholdes til de ruller ut</span><span>kontrastlinje = faktisk pris · høyre = pris</span>
      </div>
      <div class="pg-forecast-meta"><strong>{interval}</strong> · {horizon} · {latest_snapshot.status}{degradation} · {actual_label}</div>
    </div>'''
    return "".join(line.strip() for line in fragment.splitlines())
