from __future__ import annotations

from statistics import median
from typing import Iterable

from adaptation_statistics import summarize_adaptation_diagnostics
from forecast_error import ForecastErrorObservation


DEFAULT_SMOOTHING_WINDOW = 5
VISUAL_ERROR_LIMIT = 3.0


def _rolling_median(values: list[float], *, window: int = DEFAULT_SMOOTHING_WINDOW) -> list[float]:
    size = max(1, int(window))
    result: list[float] = []
    for index in range(len(values)):
        start = max(0, index - size + 1)
        result.append(float(median(values[start : index + 1])))
    return result


def _clip(value: float, limit: float = VISUAL_ERROR_LIMIT) -> float:
    bound = max(1.0, float(limit))
    return max(-bound, min(bound, float(value)))


def _context(item):
    return getattr(item, "adaptation_context", None)


def _context_text(item) -> str:
    context = _context(item)
    if context is None or not context.has_context:
        return ""
    parts: list[str] = []
    if context.response_count:
        parts.append(
            f"response {context.response_count}: {context.divergent_count} divergent, "
            f"{context.aligned_count} aligned"
        )
    if context.transmission_count:
        parts.append(
            f"transmission {context.transmission_count}: {context.resolved_count} resolved, "
            f"{context.unresolved_count} unresolved"
        )
    if context.dominant_channels:
        parts.append("kanaler " + ", ".join(context.dominant_channels))
    return " · ".join(parts) + " · tidsmessig kontekst, ikke kausalitet"


def _diagnostic_summary_html(usable: list[object]) -> str:
    summary = summarize_adaptation_diagnostics(usable)
    if summary.context_count == 0:
        return '<div class="pg-error-diagnostic">Adaptation diagnostics: venter på tidsmatchet response/transmission-kontekst.</div>'

    pieces: list[str] = []
    if summary.divergence_comparison_ready:
        delta = summary.divergence_error_delta
        assert delta is not None
        pieces.append(
            f"divergence median |feil| {summary.median_abs_error_divergence:.2f} "
            f"vs uten divergence {summary.median_abs_error_nondivergence:.2f} "
            f"(Δ {delta:+.2f}; n={summary.divergence_count}/{summary.nondivergence_count})"
        )
    else:
        pieces.append(
            f"divergence-sammenligning: for lite data "
            f"(n={summary.divergence_count}/{summary.nondivergence_count}, trenger minst {summary.min_group_size}/{summary.min_group_size})"
        )

    if summary.transmission_comparison_ready:
        delta = summary.transmission_error_delta
        assert delta is not None
        pieces.append(
            f"uavklart transmisjon median |feil| {summary.median_abs_error_unresolved:.2f} "
            f"vs resolved {summary.median_abs_error_resolved:.2f} "
            f"(Δ {delta:+.2f}; n={summary.unresolved_count}/{summary.resolved_count})"
        )
    else:
        pieces.append(
            f"transmisjonssammenligning: for lite data "
            f"(n={summary.unresolved_count}/{summary.resolved_count}, trenger minst {summary.min_group_size}/{summary.min_group_size})"
        )

    return (
        '<div class="pg-error-diagnostic">'
        + " · ".join(pieces)
        + " · deskriptivt, ingen kausalitet eller læringsvekt"
        + "</div>"
    )


def render_forecast_error_track(
    observations: Iterable[ForecastErrorObservation],
    *,
    smoothing_window: int = DEFAULT_SMOOTHING_WINDOW,
) -> str:
    """Render signed model error plus descriptive adaptation context."""
    usable = [item for item in observations if item.normalized_center_error is not None]
    usable.sort(key=lambda item: (item.forecast_as_of, item.error_id))
    if not usable:
        return (
            '<div class="pg-error-track pg-error-empty">'
            '<span>MODELLFEIL</span><span>Venter på modne forecasts for valgt horisont.</span>'
            '</div>'
        )

    raw = [float(item.normalized_center_error) for item in usable]
    smooth = _rolling_median(raw, window=smoothing_window)
    width = 100.0
    height = 36.0
    pad_x = 2.0
    mid_y = height / 2.0
    scale_y = (height * 0.40) / VISUAL_ERROR_LIMIT

    def x_at(index: int) -> float:
        if len(raw) <= 1:
            return width / 2.0
        return pad_x + (width - 2.0 * pad_x) * (index / (len(raw) - 1))

    def y_at(value: float) -> float:
        return mid_y - _clip(value) * scale_y

    raw_dots: list[str] = []
    context_markers: list[str] = []
    for index, (value, item) in enumerate(zip(raw, usable)):
        context_text = _context_text(item)
        title = f"{item.forecast_as_of} · feil {value:+.2f} intervallbredder · {item.classification}"
        if context_text:
            title += " · " + context_text
        x = x_at(index)
        y = y_at(value)
        raw_dots.append(
            f'<circle class="pg-error-dot" cx="{x:.3f}" cy="{y:.3f}" r="0.72">'
            f'<title>{title}</title></circle>'
        )
        context = _context(item)
        if context is not None and context.saw_divergence:
            context_markers.append(
                f'<circle class="pg-error-context-divergent" cx="{x:.3f}" cy="{y:.3f}" r="1.55" '
                'style="fill:none;stroke:currentColor;stroke-width:.48;stroke-opacity:.58;vector-effect:non-scaling-stroke">'
                f'<title>Divergence observert mens forecastet var levende · {context_text}</title></circle>'
            )
        if context is not None and context.saw_unresolved_transmission:
            size = 1.15
            points = f"{x:.3f},{y-size:.3f} {x+size:.3f},{y:.3f} {x:.3f},{y+size:.3f} {x-size:.3f},{y:.3f}"
            context_markers.append(
                f'<polygon class="pg-error-context-unresolved" points="{points}" '
                'style="fill:currentColor;fill-opacity:.28;stroke:none">'
                f'<title>Uavklart transmisjon observert mens forecastet var levende · {context_text}</title></polygon>'
            )

    smooth_points = " ".join(
        f"{x_at(index):.3f},{y_at(value):.3f}" for index, value in enumerate(smooth)
    )
    contexts = [_context(item) for item in usable]
    contexts_with_data = sum(context is not None and context.has_context for context in contexts)
    divergence_linked = sum(context is not None and context.saw_divergence for context in contexts)
    unresolved_linked = sum(context is not None and context.saw_unresolved_transmission for context in contexts)
    latest = raw[-1]
    latest_smooth = smooth[-1]
    latest_class = usable[-1].classification
    context_summary = ""
    if contexts_with_data:
        context_summary = (
            f" · kontekst {contexts_with_data} · divergence {divergence_linked} · "
            f"uavklart transmisjon {unresolved_linked}"
        )
    diagnostic_html = _diagnostic_summary_html(usable)
    return f"""
      <div class="pg-error-track">
        <div class="pg-error-head">
          <span>MODELLFEIL · SIGNERT</span>
          <span>{len(usable)} modne · median {smoothing_window} · siste {latest:+.2f}{context_summary}</span>
        </div>
        <svg class="pg-error-svg" viewBox="0 0 100 36" preserveAspectRatio="none" role="img" aria-label="Historisk signert forecastfeil med read-only adaptation context">
          <line class="pg-error-bound" x1="0" x2="100" y1="{y_at(1.0):.3f}" y2="{y_at(1.0):.3f}" />
          <line class="pg-error-zero" x1="0" x2="100" y1="{mid_y:.3f}" y2="{mid_y:.3f}" />
          <line class="pg-error-bound" x1="0" x2="100" y1="{y_at(-1.0):.3f}" y2="{y_at(-1.0):.3f}" />
          {''.join(raw_dots)}
          {''.join(context_markers)}
          <polyline class="pg-error-median" points="{smooth_points}" />
        </svg>
        <div class="pg-error-foot">
          <span>−1 = nedre forecastgrense · 0 = intervalsentrum · +1 = øvre forecastgrense</span>
          <span>ring = divergence · diamant = uavklart transmisjon · median {latest_smooth:+.2f} · {latest_class}</span>
        </div>
        {diagnostic_html}
      </div>
    """
