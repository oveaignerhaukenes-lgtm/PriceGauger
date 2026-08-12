from __future__ import annotations

from statistics import median

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


def render_forecast_error_track(
    observations: tuple[ForecastErrorObservation, ...] | list[ForecastErrorObservation],
    *,
    smoothing_window: int = DEFAULT_SMOOTHING_WINDOW,
) -> str:
    """Render a compact signed model-error track for one market × horizon family.

    Raw completed forecast errors remain immutable and are drawn faintly. The solid
    line is only a display-time rolling median; it is never persisted and never
    feeds Decision State. Zero means the realized move landed at the frozen
    interval centre, while +/-1 correspond to the frozen interval bounds.
    """
    usable = [
        item
        for item in observations
        if item.normalized_center_error is not None
    ]
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
    for index, (value, item) in enumerate(zip(raw, usable)):
        title = (
            f"{item.forecast_as_of} · feil {value:+.2f} intervallbredder · "
            f"{item.classification}"
        )
        raw_dots.append(
            f'<circle class="pg-error-dot" cx="{x_at(index):.3f}" cy="{y_at(value):.3f}" r="0.72">'
            f'<title>{title}</title></circle>'
        )

    smooth_points = " ".join(
        f"{x_at(index):.3f},{y_at(value):.3f}" for index, value in enumerate(smooth)
    )
    latest = raw[-1]
    latest_smooth = smooth[-1]
    latest_class = usable[-1].classification
    return f"""
      <div class="pg-error-track">
        <div class="pg-error-head">
          <span>MODELLFEIL · SIGNERT</span>
          <span>{len(usable)} modne · median {smoothing_window} · siste {latest:+.2f}</span>
        </div>
        <svg class="pg-error-svg" viewBox="0 0 100 36" preserveAspectRatio="none" role="img" aria-label="Historisk signert forecastfeil">
          <line class="pg-error-bound" x1="0" x2="100" y1="{y_at(1.0):.3f}" y2="{y_at(1.0):.3f}" />
          <line class="pg-error-zero" x1="0" x2="100" y1="{mid_y:.3f}" y2="{mid_y:.3f}" />
          <line class="pg-error-bound" x1="0" x2="100" y1="{y_at(-1.0):.3f}" y2="{y_at(-1.0):.3f}" />
          {''.join(raw_dots)}
          <polyline class="pg-error-median" points="{smooth_points}" />
        </svg>
        <div class="pg-error-foot">
          <span>−1 = nedre forecastgrense · 0 = intervalsentrum · +1 = øvre forecastgrense</span>
          <span>median {latest_smooth:+.2f} · {latest_class}</span>
        </div>
      </div>
    """
