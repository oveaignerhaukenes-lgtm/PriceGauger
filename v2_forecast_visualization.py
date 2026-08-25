from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone
from typing import Iterable


def _utc(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _sample(points: tuple, limit: int = 180) -> tuple:
    if len(points) <= limit:
        return points
    last = len(points) - 1
    indexes = sorted({round(index * last / (limit - 1)) for index in range(limit)})
    return tuple(points[index] for index in indexes)


def _path_progress(shape: str, progress: float) -> float:
    p = max(0.0, min(1.0, float(progress)))
    normalized = str(shape or "").upper()
    if normalized == "TREND_CONTINUATION":
        return p ** 0.85
    if normalized == "MEAN_REVERTING_OR_RANGE":
        return p * (1.10 - 0.10 * p)
    return p


def _profile_return(item, progress: float) -> float:
    p = max(0.0, min(1.0, float(progress)))
    raw = tuple(getattr(item, "path_profile", ()) or ())
    profile: list[tuple[float, float]] = []
    for point in raw:
        try:
            x, value = point
            profile.append((max(0.0, min(1.0, float(x))), float(value)))
        except (TypeError, ValueError):
            continue
    profile.sort(key=lambda point: point[0])
    if not profile:
        return float(item.expected_return) * _path_progress(item.path_shape, p)
    if p <= profile[0][0]:
        return profile[0][1]
    if p >= profile[-1][0]:
        return profile[-1][1]
    for left, right in zip(profile, profile[1:]):
        if left[0] <= p <= right[0]:
            span = max(1e-12, right[0] - left[0])
            ratio = (p - left[0]) / span
            return left[1] + (right[1] - left[1]) * ratio
    return profile[-1][1]


def _path_return(view, progress: float) -> float:
    return _profile_return(view, progress)


def _points(points: Iterable[tuple[float, float]]) -> str:
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in points)


def _state_label(value: str) -> str:
    return str(value or "UNDETERMINED").replace("_", " ")


def _history_reference(parsed_history: list[tuple[datetime, float]], when: datetime) -> float | None:
    candidates = [price for stamp, price in parsed_history if stamp <= when]
    return None if not candidates else float(candidates[-1])


def _forecast_history_window(
    full_history: list[tuple[datetime, float]],
    ghosts: tuple,
) -> list[tuple[datetime, float]]:
    """Keep enough context to compare recent forecasts without compressing them into pixels.

    The read model may carry weeks/months of price history. Historical forecast ghosts
    usually span only hours or days. This renderer therefore chooses a display window
    around the oldest visible ghost while preserving the full history separately for
    T0 anchoring. The chart is an evaluation surface, not a long-range context chart.
    """
    if not full_history or not ghosts:
        return list(_sample(tuple(full_history)))

    first_available = full_history[0][0]
    last_available = full_history[-1][0]
    valid: list[tuple[datetime, int]] = []
    for ghost in ghosts:
        start = _utc(getattr(ghost, "as_of", None))
        if start is None or start < first_available or start > last_available:
            continue
        try:
            horizon = max(1, int(getattr(ghost, "horizon_seconds", 1)))
        except (TypeError, ValueError):
            horizon = 1
        valid.append((start, horizon))
    if not valid:
        return list(_sample(tuple(full_history)))

    earliest = min(start for start, _ in valid)
    max_horizon = max(horizon for _, horizon in valid)
    ghost_span = max(float(max_horizon), (last_available - earliest).total_seconds())
    padding_seconds = max(900.0, float(max_horizon) * 0.35, ghost_span * 0.15)
    window_start = max(first_available, earliest - timedelta(seconds=padding_seconds))
    visible = [item for item in full_history if item[0] >= window_start]
    return list(_sample(tuple(visible)))


def render_v2_forecast_chart(view) -> str:
    raw_history = tuple(getattr(view, "price_history", ()) or ())
    full_history: list[tuple[datetime, float]] = []
    for stamp, price in raw_history:
        parsed = _utc(stamp)
        if parsed is not None:
            full_history.append((parsed, float(price)))
    full_history.sort(key=lambda item: item[0])

    ghosts = tuple(getattr(view, "forecast_ghosts", ()) or ())[-10:]
    parsed_history = _forecast_history_window(full_history, ghosts)

    reference_price = full_history[-1][1] if full_history else 100.0
    history_prices = [price for _, price in parsed_history]
    expected_return = float(view.expected_return)
    lower_return = float(view.lower_return)
    upper_return = float(view.upper_return)
    baseline_return = float(getattr(view, "baseline_return", expected_return))

    step_count = 16
    forecast_raw: list[tuple[float, float]] = []
    lower_raw: list[tuple[float, float]] = []
    upper_raw: list[tuple[float, float]] = []
    baseline_raw: list[tuple[float, float]] = []
    for index in range(step_count + 1):
        p = index / step_count
        path_return = _path_return(view, p)
        x = 66.0 + 31.0 * p
        center = reference_price * (1.0 + path_return)
        low = reference_price * (1.0 + path_return + (lower_return - expected_return) * p)
        high = reference_price * (1.0 + path_return + (upper_return - expected_return) * p)
        baseline = reference_price * (1.0 + baseline_return * _path_progress(view.path_shape, p))
        forecast_raw.append((x, center))
        lower_raw.append((x, low))
        upper_raw.append((x, high))
        baseline_raw.append((x, baseline))

    ghost_raw: list[tuple[list[tuple[datetime, float]], list[tuple[datetime, float]], list[tuple[datetime, float]]]] = []
    if full_history:
        history_last = full_history[-1][0]
        for ghost in ghosts:
            ghost_start = _utc(ghost.as_of)
            if ghost_start is None or ghost_start < full_history[0][0] or ghost_start > history_last:
                continue
            ghost_reference = _history_reference(full_history, ghost_start)
            if ghost_reference is None:
                continue
            horizon = max(1, int(ghost.horizon_seconds))
            ghost_end = ghost_start + timedelta(seconds=horizon)
            visible_end = min(ghost_end, history_last)
            visible_fraction = max(0.0, min(1.0, (visible_end - ghost_start).total_seconds() / horizon))
            if visible_fraction <= 0.0:
                continue
            center_points: list[tuple[datetime, float]] = []
            low_points: list[tuple[datetime, float]] = []
            high_points: list[tuple[datetime, float]] = []
            for index in range(step_count + 1):
                p = visible_fraction * index / step_count
                stamp = ghost_start + timedelta(seconds=horizon * p)
                path_return = _profile_return(ghost, p)
                center = ghost_reference * (1.0 + path_return)
                low = ghost_reference * (
                    1.0 + path_return + (float(ghost.lower_return) - float(ghost.expected_return)) * p
                )
                high = ghost_reference * (
                    1.0 + path_return + (float(ghost.upper_return) - float(ghost.expected_return)) * p
                )
                center_points.append((stamp, center))
                low_points.append((stamp, low))
                high_points.append((stamp, high))
            ghost_raw.append((center_points, low_points, high_points))

    ghost_prices = [
        price
        for center_points, low_points, high_points in ghost_raw
        for _, price in (*center_points, *low_points, *high_points)
    ]
    scale_values = history_prices + ghost_prices + [price for _, price in lower_raw] + [price for _, price in upper_raw]
    if not scale_values:
        scale_values = [reference_price]
    low_price = min(scale_values)
    high_price = max(scale_values)
    span = max(high_price - low_price, abs(reference_price) * 0.001, 0.01)
    low_price -= span * 0.10
    high_price += span * 0.10

    def ymap(price: float) -> float:
        return 92.0 - (float(price) - low_price) / (high_price - low_price) * 80.0

    history_xy: list[tuple[float, float]] = []
    first = parsed_history[0][0] if parsed_history else None
    last = parsed_history[-1][0] if parsed_history else None
    duration = max(1.0, (last - first).total_seconds()) if first is not None and last is not None else 1.0

    def history_x(stamp: datetime) -> float:
        assert first is not None
        return 2.0 + 63.0 * (stamp - first).total_seconds() / duration

    if parsed_history:
        for stamp, price in parsed_history:
            history_xy.append((history_x(stamp), ymap(price)))

    forecast_xy = [(x, ymap(price)) for x, price in forecast_raw]
    lower_xy = [(x, ymap(price)) for x, price in lower_raw]
    upper_xy = [(x, ymap(price)) for x, price in upper_raw]
    baseline_xy = [(x, ymap(price)) for x, price in baseline_raw]
    fan = _points(tuple(upper_xy) + tuple(reversed(lower_xy)))

    ghost_fan_parts: list[str] = []
    ghost_path_parts: list[str] = []
    ghost_count = len(ghost_raw)
    for index, (center_points, low_points, high_points) in enumerate(ghost_raw):
        if first is None:
            break
        rank = (index + 1) / max(1, ghost_count)
        line_opacity = 0.20 + 0.38 * rank
        fan_opacity = 0.035 + 0.085 * rank
        center_xy = [(history_x(stamp), ymap(price)) for stamp, price in center_points]
        low_xy = [(history_x(stamp), ymap(price)) for stamp, price in low_points]
        high_xy = [(history_x(stamp), ymap(price)) for stamp, price in high_points]
        ghost_fan = _points(tuple(high_xy) + tuple(reversed(low_xy)))
        ghost_fan_parts.append(
            f'<polygon class="pg-v2-ghost-fan" style="fill-opacity:{fan_opacity:.3f}" points="{ghost_fan}" />'
        )
        ghost_path_parts.append(
            f'<polyline class="pg-v2-ghost-path" style="stroke-opacity:{line_opacity:.3f}" points="{_points(center_xy)}" />'
        )
    ghost_fans = "".join(ghost_fan_parts)
    ghost_paths = "".join(ghost_path_parts)

    history_markup = ""
    if len(history_xy) >= 2:
        history_markup = f'<polyline class="pg-v2-history" points="{_points(history_xy)}" />'

    baseline_markup = ""
    if getattr(view, "applied_layers", ()) and abs(baseline_return - expected_return) > 1e-12:
        baseline_markup = (
            f'<polyline class="pg-v2-baseline-compare" points="{_points(baseline_xy)}">'
            '<title>TA-only baseline</title></polyline>'
        )

    interval = f"{lower_return * 100:+.3f}% … {upper_return * 100:+.3f}%"
    expected = f"{expected_return * 100:+.3f}%"
    recipe = html.escape(str(view.recipe_label))
    delay = getattr(view, "feed_delay_minutes", None)
    delay_label = "live" if delay is None or float(delay) <= 0 else f"delay {float(delay):g}m"
    header_right = f"{recipe} · {html.escape(delay_label)}"
    path = html.escape(_state_label(view.path_shape))
    ghost_note = f" · {ghost_count} ghosts" if ghost_count else ""
    empty_note = "" if parsed_history else '<span class="pg-v2-note">Ingen canonical prishistorikk i read-modellen; grafen er indeksert til 100.</span>'

    return (
        '<div class="pg-v2-chart" data-recipe="' + recipe + '">'
        '<div class="pg-v2-chart-head"><span>PROGNOSE VS. VIRKELIGHET</span>'
        f'<span>{header_right}</span></div>'
        '<div class="pg-v2-zones"><span>HISTORIKK' + ghost_note + '</span><span>NÅ → PROGNOSE</span></div>'
        '<svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" '
        'aria-label="Persisted v2 technical forecast with observed history, historical forecasts and uncertainty">'
        '<line class="pg-v2-now" x1="66" x2="66" y1="7" y2="95" />'
        f'{ghost_fans}'
        f'<polygon class="pg-v2-fan" points="{fan}" />'
        f'{history_markup}'
        f'{ghost_paths}'
        f'{baseline_markup}'
        f'<polyline class="pg-v2-path" points="{_points(forecast_xy)}" />'
        '</svg>'
        '<div class="pg-v2-chart-foot">'
        f'<span>forventet <strong>{expected}</strong> · intervall {interval}</span>'
        f'<span>{path}</span></div>{empty_note}</div>'
    )


def render_v2_technical_explanation(view) -> str:
    applied = tuple(getattr(view, "applied_layers", ()) or ())
    layer_text = "Technicals" if not applied else "Technicals + Technical Interpreter"
    interpreter = ""
    if applied and getattr(view, "interpreter_summary", None):
        confidence = getattr(view, "interpreter_confidence", None)
        confidence_text = "" if confidence is None else f" · {float(confidence):.0%} confidence"
        interpreter = (
            '<div class="pg-v2-interpreter"><strong>Technical Interpreter</strong>'
            f'<br>{html.escape(str(view.interpreter_summary))}{confidence_text}</div>'
        )

    rationale = str(getattr(view, "path_rationale", "") or "").strip()
    if rationale:
        path_basis = html.escape(rationale)
    else:
        path_basis = (
            "Samlet teknisk score bestemmer retning; volatilitet og horisont skalerer forventet move; "
            "confidence skalerer uncertainty."
        )

    return (
        '<div class="pg-v2-explain">'
        f'<div class="pg-v2-recipe">{html.escape(layer_text)} · {html.escape(str(view.recipe_label))}</div>'
        '<div class="pg-v2-state-grid">'
        f'<div><small>Trend</small><strong>{html.escape(_state_label(view.trend_state))}</strong></div>'
        f'<div><small>Momentum</small><strong>{html.escape(_state_label(view.momentum_state))}</strong></div>'
        f'<div><small>Struktur</small><strong>{html.escape(_state_label(view.structure_state))}</strong></div>'
        f'<div><small>Volatilitet</small><strong>{html.escape(_state_label(view.volatility_state))}</strong></div>'
        f'<div><small>TA-score</small><strong>{float(view.technical_score):+.2f}</strong></div>'
        f'<div><small>Confidence</small><strong>{float(view.confidence):.0%}</strong></div>'
        '</div>'
        f'<p class="pg-v2-driver"><strong>Banegrunnlag:</strong> {path_basis}</p>'
        f'{interpreter}</div>'
    )


V2_FORECAST_CSS = """
<style>
.pg-v2-layout{display:grid;grid-template-columns:minmax(0,2.2fr) minmax(16rem,1fr);gap:.8rem;align-items:stretch}
.pg-v2-chart,.pg-v2-explain{border:1px solid rgba(128,128,128,.24);border-radius:.7rem;background:rgba(128,128,128,.025);padding:.65rem .75rem}
.pg-v2-chart-head,.pg-v2-chart-foot,.pg-v2-zones{display:flex;justify-content:space-between;gap:.6rem;font-size:.66rem;line-height:1.25}
.pg-v2-chart-head{font-weight:760;letter-spacing:.055em;opacity:.74}.pg-v2-zones{font-size:.56rem;font-weight:700;opacity:.55;margin-top:.25rem}.pg-v2-zones span:last-child{width:32%;text-align:center}
.pg-v2-chart svg{display:block;width:100%;height:12rem;margin:.05rem 0}.pg-v2-now{stroke:rgba(71,85,105,.7);stroke-width:.8;stroke-dasharray:2 1.4;vector-effect:non-scaling-stroke}.pg-v2-history{fill:none;stroke:currentColor;stroke-width:1.55;vector-effect:non-scaling-stroke}.pg-v2-fan{fill:var(--primary-color,#4f6f9f);fill-opacity:.13;stroke:none}.pg-v2-path{fill:none;stroke:var(--primary-color,#355f91);stroke-width:2;vector-effect:non-scaling-stroke}.pg-v2-ghost-fan{fill:var(--primary-color,#4f6f9f);stroke:none}.pg-v2-ghost-path{fill:none;stroke:var(--primary-color,#355f91);stroke-width:1.3;stroke-dasharray:1.7 1.15;vector-effect:non-scaling-stroke}.pg-v2-baseline-compare{fill:none;stroke:rgba(100,116,139,.72);stroke-width:1;stroke-dasharray:2 1.5;vector-effect:non-scaling-stroke}.pg-v2-note{display:block;font-size:.58rem;opacity:.6;margin-top:.2rem}
.pg-v2-recipe{font-size:.68rem;font-weight:760;letter-spacing:.035em;opacity:.7;margin-bottom:.6rem}.pg-v2-state-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.45rem}.pg-v2-state-grid div{border-top:1px solid rgba(128,128,128,.18);padding-top:.3rem}.pg-v2-state-grid small{display:block;font-size:.59rem;opacity:.62}.pg-v2-state-grid strong{display:block;font-size:.77rem;margin-top:.05rem}.pg-v2-driver{font-size:.72rem;line-height:1.4;margin:.65rem 0 0}.pg-v2-interpreter{font-size:.71rem;line-height:1.4;margin-top:.55rem;padding:.5rem;border-radius:.45rem;background:rgba(128,128,128,.07)}
@media(max-width:900px){.pg-v2-layout{grid-template-columns:1fr}.pg-v2-chart svg{height:9.5rem}}
</style>
"""
