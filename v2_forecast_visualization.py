from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Iterable


def _utc(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _sample(points: tuple[tuple[str, float], ...], limit: int = 180) -> tuple[tuple[str, float], ...]:
    if len(points) <= limit:
        return points
    last = len(points) - 1
    indexes = sorted({round(index * last / (limit - 1)) for index in range(limit)})
    return tuple(points[index] for index in indexes)


def _path_progress(shape: str, progress: float) -> float:
    """Compatibility fallback for views that predate explicit path profiles."""
    p = max(0.0, min(1.0, float(progress)))
    normalized = str(shape or "").upper()
    if normalized == "TREND_CONTINUATION":
        return p ** 0.85
    if normalized == "MEAN_REVERTING_OR_RANGE":
        return p * (1.10 - 0.10 * p)
    return p


def _path_return(view, progress: float) -> float:
    """Interpolate the explicit read-model path; never infer new analysis here."""
    p = max(0.0, min(1.0, float(progress)))
    raw = tuple(getattr(view, "path_profile", ()) or ())
    profile: list[tuple[float, float]] = []
    for item in raw:
        try:
            x, value = item
            profile.append((max(0.0, min(1.0, float(x))), float(value)))
        except (TypeError, ValueError):
            continue
    profile.sort(key=lambda item: item[0])
    if not profile:
        return float(view.expected_return) * _path_progress(view.path_shape, p)
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


def _points(points: Iterable[tuple[float, float]]) -> str:
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in points)


def _state_label(value: str) -> str:
    return str(value or "UNDETERMINED").replace("_", " ")


def render_v2_forecast_chart(view) -> str:
    """Render one persisted/composed v2 forecast without running analysis.

    Terminal return and uncertainty remain authoritative. Intermediate geometry is
    consumed from the explicit v2 read-model ``path_profile``. Older callers fall
    back to the historical coarse path-shape interpolation for compatibility.
    """
    history = _sample(tuple(getattr(view, "price_history", ()) or ()))
    parsed_history: list[tuple[datetime, float]] = []
    for stamp, price in history:
        parsed = _utc(stamp)
        if parsed is not None:
            parsed_history.append((parsed, float(price)))
    parsed_history.sort(key=lambda item: item[0])

    reference_price = parsed_history[-1][1] if parsed_history else 100.0
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

    scale_values = history_prices + [price for _, price in lower_raw] + [price for _, price in upper_raw]
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
    if parsed_history:
        first = parsed_history[0][0]
        last = parsed_history[-1][0]
        duration = max(1.0, (last - first).total_seconds())
        for stamp, price in parsed_history:
            x = 2.0 + 63.0 * (stamp - first).total_seconds() / duration
            history_xy.append((x, ymap(price)))

    forecast_xy = [(x, ymap(price)) for x, price in forecast_raw]
    lower_xy = [(x, ymap(price)) for x, price in lower_raw]
    upper_xy = [(x, ymap(price)) for x, price in upper_raw]
    baseline_xy = [(x, ymap(price)) for x, price in baseline_raw]
    fan = _points(tuple(upper_xy) + tuple(reversed(lower_xy)))

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
    path = html.escape(_state_label(view.path_shape))
    empty_note = "" if parsed_history else '<span class="pg-v2-note">Ingen canonical prishistorikk i read-modellen; grafen er indeksert til 100.</span>'

    return (
        '<div class="pg-v2-chart" data-recipe="' + recipe + '">'
        '<div class="pg-v2-chart-head"><span>PROGNOSE VS. VIRKELIGHET</span>'
        f'<span>{recipe}</span></div>'
        '<div class="pg-v2-zones"><span>HISTORIKK</span><span>NÅ → PROGNOSE</span></div>'
        '<svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" '
        'aria-label="Persisted v2 technical forecast with observed price history and uncertainty">'
        '<line class="pg-v2-now" x1="66" x2="66" y1="7" y2="95" />'
        f'<polygon class="pg-v2-fan" points="{fan}" />'
        f'{history_markup}{baseline_markup}'
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
.pg-v2-chart svg{display:block;width:100%;height:12rem;margin:.05rem 0}.pg-v2-now{stroke:rgba(71,85,105,.7);stroke-width:.8;stroke-dasharray:2 1.4;vector-effect:non-scaling-stroke}.pg-v2-history{fill:none;stroke:currentColor;stroke-width:1.55;vector-effect:non-scaling-stroke}.pg-v2-fan{fill:var(--primary-color,#4f6f9f);fill-opacity:.13;stroke:none}.pg-v2-path{fill:none;stroke:var(--primary-color,#355f91);stroke-width:2;vector-effect:non-scaling-stroke}.pg-v2-baseline-compare{fill:none;stroke:rgba(100,116,139,.72);stroke-width:1;stroke-dasharray:2 1.5;vector-effect:non-scaling-stroke}.pg-v2-note{display:block;font-size:.58rem;opacity:.6;margin-top:.2rem}
.pg-v2-recipe{font-size:.68rem;font-weight:760;letter-spacing:.035em;opacity:.7;margin-bottom:.6rem}.pg-v2-state-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.45rem}.pg-v2-state-grid div{border-top:1px solid rgba(128,128,128,.18);padding-top:.3rem}.pg-v2-state-grid small{display:block;font-size:.59rem;opacity:.62}.pg-v2-state-grid strong{display:block;font-size:.77rem;margin-top:.05rem}.pg-v2-driver{font-size:.72rem;line-height:1.4;margin:.65rem 0 0}.pg-v2-interpreter{font-size:.71rem;line-height:1.4;margin-top:.55rem;padding:.5rem;border-radius:.45rem;background:rgba(128,128,128,.07)}
@media(max-width:900px){.pg-v2-layout{grid-template-columns:1fr}.pg-v2-chart svg{height:9.5rem}}
</style>
"""
