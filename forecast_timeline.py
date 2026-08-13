from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import ceil, floor, log10
from typing import Iterable

from forecast_contracts import ForecastSnapshot
from forecast_path import ForecastPathEvidence, analysis_path_move, transient_path_uncertainty_pct
from forecast_visuals import MISSING_INPUT_LABELS


MIN_FORECAST_HORIZON = timedelta(minutes=1)


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
    """Legacy qualitative label only; it must not become forecast evidence."""
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
    """Legacy endpoint interpolation retained for historical v1 snapshots."""
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
    horizon = max(MIN_FORECAST_HORIZON, timedelta(hours=float(snapshot.horizon_hours)))
    return TimelineForecast(snapshot=snapshot, as_of=as_of, ends_at=as_of + horizon)


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


def _observed_price_at(
    observed: tuple[tuple[datetime, float], ...],
    stamp: datetime,
    *,
    max_gap: timedelta = timedelta(minutes=5),
) -> float | None:
    """Interpolate canonical observed price only across a genuinely continuous gap."""
    if not observed or stamp < observed[0][0] or stamp > observed[-1][0]:
        return None
    previous: tuple[datetime, float] | None = None
    for current in observed:
        if current[0] == stamp:
            return float(current[1])
        if current[0] > stamp:
            if previous is None or current[0] - previous[0] > max_gap:
                return None
            span = (current[0] - previous[0]).total_seconds()
            if span <= 0:
                return float(previous[1])
            progress = (stamp - previous[0]).total_seconds() / span
            return float(previous[1]) + (float(current[1]) - float(previous[1])) * progress
        previous = current
    return None


def _history_evaluation_strength(x: float, *, split_x: float) -> float:
    """Fade forecast geometry into outcome error over the older half of history."""
    if split_x <= 0 or x >= split_x:
        return 0.0
    age = max(0.0, min(1.0, 1.0 - x / split_x))
    return max(0.0, min(1.0, (age - 0.45) / 0.55))


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
        return (float(round((lower + upper) / 2.0)),)
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
    """Use bounded chart history while retaining the latest forecast endpoint."""
    latest = candidates[-1]
    horizon = max(MIN_FORECAST_HORIZON, latest.ends_at - latest.as_of)
    axis_end = latest.ends_at
    if observed:
        axis_end = max(axis_end, observed[-1][0])
        axis_start = min(axis_end - 2 * horizon, observed[0][0])
    else:
        axis_start = axis_end - 2 * horizon
    return axis_start, axis_end


def _horizon_label(hours: float | None) -> str:
    if hours is None:
        return "?"
    value = float(hours)
    if value < 1.0:
        return f"{round(value * 60):g}m"
    if abs(value - 168.0) <= 1e-6:
        return "7d"
    return f"{value:g}t"


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
    """Render immutable forecasts against canonical realized prices.

    Historical layers retain stable endpoint interpolation because their exact
    technical path evidence is not persisted yet. The newest active layer uses
    the current persisted Decision State plus technical regime/volatility passed
    by Overview, so the projected path may express alignment, counter-momentum
    and intrahorizon uncertainty without inventing stochastic wiggles.
    """
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
    latest_forecast = candidates[-1]
    horizon = max(MIN_FORECAST_HORIZON, latest_forecast.ends_at - latest_forecast.as_of)
    trail_start = latest_forecast.as_of - 2 * horizon
    layers = [item for item in candidates if item.ends_at >= trail_start and item.as_of <= axis_end]
    if max_layers is not None:
        layers = layers[-max(1, int(max_layers)) :]

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    split_time = current if axis_start < current < axis_end else latest_forecast.as_of

    observed_in_window = tuple(item for item in observed if axis_start <= item[0] <= axis_end)
    gaps = _timeline_gaps(observed)
    plot_right = 90.0
    split_x = 64.0
    history_span = max(1.0, _display_seconds(split_time, axis_start=axis_start, gaps=gaps))
    future_span = max(1.0, _display_seconds(axis_end, axis_start=split_time, gaps=gaps))

    def xmap(stamp: datetime) -> float:
        if stamp <= split_time:
            displayed = _display_seconds(stamp, axis_start=axis_start, gaps=gaps)
            return max(0.0, min(split_x, displayed / history_span * split_x))
        displayed = _display_seconds(stamp, axis_start=split_time, gaps=gaps)
        return max(split_x, min(plot_right, split_x + displayed / future_span * (plot_right - split_x)))

    plotted_layers: list[dict[str, object]] = []
    layer_count = len(layers)
    evidence = ForecastPathEvidence(market_regime=market_regime, volatility_score=volatility_score)
    for index, item in enumerate(layers):
        snapshot = item.snapshot
        ref = float(snapshot.reference_price)
        low = float(snapshot.expected_move_low_pct)
        high = float(snapshot.expected_move_high_pct)
        base_end = (low + high) / 2.0
        is_active = index == layer_count - 1
        base: list[tuple[float, float]] = []
        base_timed: list[tuple[datetime, float, float]] = []
        bull: list[tuple[float, float]] = []
        bear: list[tuple[float, float]] = []
        upper: list[tuple[float, float]] = []
        lower: list[tuple[float, float]] = []
        low_evidence = snapshot.status != "READY" or float(snapshot.confidence) < 0.55
        fan_exponent = 0.45 if low_evidence else 0.8
        step_count = max(2, int(steps))
        for step in range(step_count + 1):
            progress = step / step_count
            stamp = item.as_of + (item.ends_at - item.as_of) * progress
            x = xmap(stamp)
            if is_active:
                base_move = analysis_path_move(
                    progress,
                    base_end,
                    decision_score=float(snapshot.direction_score),
                    confidence=float(snapshot.confidence),
                    evidence=evidence,
                )
                bull_move = analysis_path_move(
                    progress,
                    high,
                    decision_score=float(snapshot.direction_score),
                    confidence=float(snapshot.confidence),
                    evidence=evidence,
                )
                bear_move = analysis_path_move(
                    progress,
                    low,
                    decision_score=float(snapshot.direction_score),
                    confidence=float(snapshot.confidence),
                    evidence=evidence,
                )
                transient = transient_path_uncertainty_pct(
                    progress,
                    base_end,
                    confidence=float(snapshot.confidence),
                    evidence=evidence,
                )
            else:
                base_move = _shape(progress, base_end, "TREND")
                bull_move = _shape(progress, high, "TREND")
                bear_move = _shape(progress, low, "TREND")
                transient = 0.0
            fan = progress ** fan_exponent
            upper_move = base_move + max(0.0, high - base_end) * fan + transient
            lower_move = base_move - max(0.0, base_end - low) * fan - transient
            base_price = ref * (1.0 + base_move / 100.0)
            base.append((x, base_price))
            base_timed.append((stamp, x, base_price))
            bull.append((x, ref * (1.0 + bull_move / 100.0)))
            bear.append((x, ref * (1.0 + bear_move / 100.0)))
            upper.append((x, ref * (1.0 + upper_move / 100.0)))
            lower.append((x, ref * (1.0 + lower_move / 100.0)))
        plotted_layers.append(
            {
                "item": item,
                "index": index,
                "base": tuple(base),
                "base_timed": tuple(base_timed),
                "bull": tuple(bull),
                "bear": tuple(bear),
                "upper": tuple(upper),
                "lower": tuple(lower),
                "analysis_derived": is_active,
            }
        )

    scale_observed = [price for _, price in observed_in_window]
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
            f'<line x1="0" y1="{y:.1f}" x2="{plot_right:.1f}" y2="{y:.1f}" style="stroke:rgba(100,116,139,.14);stroke-width:.45;vector-effect:non-scaling-stroke" />'
        )
        axis_labels.append(
            f'<span style="position:absolute;right:.12rem;top:{y:.1f}%;transform:translateY(-50%);font-size:.64rem;font-weight:400;line-height:1;color:inherit;opacity:.82;white-space:nowrap">{tick:g}</span>'
        )
    grid_markup.append(
        '<line x1="90" y1="10" x2="90" y2="94" style="stroke:rgba(100,116,139,.25);stroke-width:.5;vector-effect:non-scaling-stroke" />'
    )
    grid_markup.append(
        f'<line x1="{split_x:.1f}" y1="5" x2="{split_x:.1f}" y2="96" class="pg-now-boundary" style="stroke:rgba(71,85,105,.78);stroke-width:.9;stroke-dasharray:1.8 1.3;vector-effect:non-scaling-stroke"><title>NÅ · observert til venstre, prognose til høyre</title></line>'
    )

    gap_markup: list[str] = []
    for gap in gaps:
        if gap.end < axis_start or gap.start > axis_end:
            continue
        left = xmap(max(axis_start, gap.start))
        right = xmap(min(axis_end, gap.end))
        width = max(1.2, right - left)
        center = min(plot_right - width / 2.0, left + width / 2.0)
        gap_markup.append(
            f'<rect x="{center - width / 2.0:.1f}" y="14" width="{width:.1f}" height="82" rx=".8" style="fill:rgba(100,116,139,.08);stroke:rgba(100,116,139,.28);stroke-width:.35;stroke-dasharray:1.2 1.2;vector-effect:non-scaling-stroke"><title>{gap.label}</title></rect>'
        )

    layer_markup: list[str] = []
    error_markup: list[str] = []
    count = len(plotted_layers)
    evaluated_layers = 0
    for ordinal, layer in enumerate(plotted_layers):
        upper = layer["upper"]
        lower = layer["lower"]
        base = layer["base"]
        fan_polygon = _points(tuple(upper) + tuple(reversed(lower)), ymap=ymap)
        fan_opacity, line_opacity = _layer_opacity(ordinal, count)
        item = layer["item"]
        start_x = xmap(item.as_of)
        history_strength = _history_evaluation_strength(start_x, split_x=split_x)
        visual_line_opacity = line_opacity * (1.0 - 0.72 * history_strength)
        visual_fan_opacity = fan_opacity * (1.0 - 0.88 * history_strength)
        analysis_class = " pg-analysis-derived-path" if layer["analysis_derived"] else ""
        layer_markup.append(
            f'<line x1="{start_x:.1f}" y1="8" x2="{start_x:.1f}" y2="96" style="stroke:{color};stroke-width:.45;stroke-opacity:{visual_line_opacity:.2f};stroke-dasharray:1.5 2;vector-effect:non-scaling-stroke" />'
        )
        layer_markup.append(
            f'<polygon points="{fan_polygon}" class="pg-forecast-layer pg-forecast-fan{analysis_class}" style="fill:{color};fill-opacity:{visual_fan_opacity:.2f};stroke:none" />'
        )
        layer_markup.append(
            f'<polyline points="{_points(base, ymap=ymap)}" class="pg-forecast-layer pg-forecast-base{analysis_class}" style="fill:none;stroke:{color};stroke-width:{1.15 if ordinal < count - 1 else 2.0};stroke-opacity:{visual_line_opacity:.2f};vector-effect:non-scaling-stroke" />'
        )

        layer_has_evaluation = False
        for stamp, x, predicted_price in layer["base_timed"]:
            if stamp > split_time:
                continue
            strength = _history_evaluation_strength(x, split_x=split_x)
            if strength <= 0.0:
                continue
            actual_price = _observed_price_at(observed, stamp)
            if actual_price is None:
                continue
            layer_has_evaluation = True
            error_markup.append(
                f'<line x1="{x:.1f}" y1="{ymap(predicted_price):.1f}" x2="{x:.1f}" y2="{ymap(actual_price):.1f}" class="pg-forecast-error" style="stroke:#b45309;stroke-width:.8;stroke-opacity:{0.12 + 0.58 * strength:.2f};vector-effect:non-scaling-stroke"><title>Prognoseavvik: {predicted_price - actual_price:+.2f}</title></line>'
            )
        if layer_has_evaluation:
            evaluated_layers += 1

    if plotted_layers:
        latest = plotted_layers[-1]
        latest_bull = tuple(point for timed, point in zip(latest["base_timed"], latest["bull"]) if timed[0] >= split_time)
        latest_bear = tuple(point for timed, point in zip(latest["base_timed"], latest["bear"]) if timed[0] >= split_time)
        if len(latest_bull) >= 2:
            layer_markup.append(
                f'<polyline points="{_points(latest_bull, ymap=ymap)}" class="pg-alt pg-bull" style="fill:none;stroke:#2f9e64;stroke-width:1.0;stroke-dasharray:2 1.4;vector-effect:non-scaling-stroke" />'
            )
        if len(latest_bear) >= 2:
            layer_markup.append(
                f'<polyline points="{_points(latest_bear, ymap=ymap)}" class="pg-alt pg-bear" style="fill:none;stroke:#d15b5b;stroke-width:1.0;stroke-dasharray:2 1.4;vector-effect:non-scaling-stroke" />'
            )

    actual_markup = ""
    if observed_in_window:
        actual_parts: list[str] = []
        for segment in _observed_segments(observed_in_window):
            segment_points = [(xmap(stamp), price) for stamp, price in segment]
            if len(segment_points) >= 2:
                actual_parts.append(
                    f'<polyline points="{_points(segment_points, ymap=ymap)}" class="pg-realized" style="fill:none;stroke:currentColor;stroke-width:1.9;vector-effect:non-scaling-stroke" />'
                )
        actual_markup = "".join(actual_parts)

    latest_snapshot = latest_forecast.snapshot
    interval = f"{latest_snapshot.expected_move_low_pct:+.2f}%…{latest_snapshot.expected_move_high_pct:+.2f}%"
    horizon_label = _horizon_label(latest_snapshot.horizon_hours)
    missing = _missing_text(latest_snapshot)
    degradation = f" · {missing}" if missing else ""
    actual_label = "faktisk pris oppdateres fra canonical 1m-bars" if observed_in_window else "venter på faktisk pris"
    status_label = f"{len(layers)} AKTIVE SPOR"
    if evaluated_layers:
        status_label += f" · {evaluated_layers} EVALUERT"

    fragment = f'''<div class="pg-forecast-wrap" style="overflow:hidden">
      <div class="pg-forecast-head"><span>PROGNOSE VS. VIRKELIGHET</span><span>{status_label}</span></div>
      <div class="pg-forecast-plot" style="position:relative;height:13.5rem">
        <svg class="pg-forecast-svg" style="height:13.5rem;display:block" viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="Markedshistorikk, evaluerte prognoser og aktiv analyseavledet prognose">
          {''.join(grid_markup)}
          {''.join(gap_markup)}
          {''.join(layer_markup)}
          {''.join(error_markup)}
          {actual_markup}
        </svg>
        <div class="pg-timeline-zones" aria-hidden="true" style="position:absolute;left:0;right:10%;top:.15rem;display:grid;grid-template-columns:64fr 26fr;pointer-events:none;font-size:.52rem;font-weight:700;letter-spacing:.05em;opacity:.62"><span>HISTORIKK · FASIT</span><span style="text-align:center">NÅ → PROGNOSE</span></div>
        <div class="pg-price-axis" aria-hidden="true" style="position:absolute;inset:0;pointer-events:none">{''.join(axis_labels)}</div>
      </div>
      <div style="display:flex;justify-content:space-between;gap:.5rem;font-size:.58rem;opacity:.72;margin-top:.08rem">
        <span>gamle prognoser fader til målt avvik · kontrastlinje = faktisk pris</span><span>aktiv bane = analyse + teknisk state</span>
      </div>
      <div class="pg-forecast-meta"><strong>{interval}</strong> · {horizon_label} · {latest_snapshot.status}{degradation} · {actual_label}</div>
    </div>'''
    return "".join(line.strip() for line in fragment.splitlines())