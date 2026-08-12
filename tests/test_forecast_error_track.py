from adaptation_diagnostics import ForecastAdaptationContext, ForecastErrorDiagnosticView
from forecast_error import ForecastErrorObservation
from forecast_error_track import _rolling_median, render_forecast_error_track


def _error(*, suffix: str, as_of: str, value: float, classification: str = "IN_INTERVAL") -> ForecastErrorObservation:
    return ForecastErrorObservation(
        error_id=f"forecast-error:{suffix}",
        forecast_id=f"forecast:{suffix}",
        market="Gold",
        horizon_hours=4.0,
        forecast_as_of=as_of,
        outcome_evaluated_at="2026-08-12T14:00:00+00:00",
        expected_low_pct=0.6,
        expected_high_pct=1.4,
        expected_center_pct=1.0,
        expected_half_width_pct=0.4,
        realized_move_pct=1.0 + 0.4 * value,
        signed_center_error_pct=0.4 * value,
        normalized_center_error=value,
        signed_interval_error_pct=0.0 if abs(value) <= 1.0 else 0.4 * (abs(value) - 1.0) * (1 if value > 0 else -1),
        normalized_interval_error=0.0 if abs(value) <= 1.0 else (abs(value) - 1.0) * (1 if value > 0 else -1),
        interval_hit=abs(value) <= 1.0,
        direction_hit=True,
        classification=classification,
    )


def _context(error_id: str) -> ForecastAdaptationContext:
    return ForecastAdaptationContext(
        error_id=error_id,
        response_count=2,
        divergent_count=1,
        aligned_count=1,
        unconfirmed_count=0,
        transmission_count=2,
        resolved_count=1,
        unresolved_count=1,
        dominant_channels=("RATES_FX",),
    )


def test_rolling_median_reduces_one_shock_without_rewriting_raw_points():
    values = [0.1, 0.2, 2.8, 0.3, 0.25]
    smooth = _rolling_median(values, window=5)
    assert smooth[-1] == 0.25
    assert values[2] == 2.8


def test_track_renders_signed_bounds_raw_observations_and_robust_median():
    errors = [
        _error(suffix="a", as_of="2026-08-12T10:00:00+00:00", value=-1.5, classification="DIRECTION_MISS"),
        _error(suffix="b", as_of="2026-08-12T11:00:00+00:00", value=0.1),
        _error(suffix="c", as_of="2026-08-12T12:00:00+00:00", value=0.2),
    ]
    html = render_forecast_error_track(errors, smoothing_window=3)
    assert "MODELLFEIL · SIGNERT" in html
    assert "3 modne" in html
    assert "−1 = nedre forecastgrense" in html
    assert html.count('class="pg-error-dot"') == 3
    assert 'class="pg-error-median"' in html
    assert "DIRECTION_MISS" in html


def test_track_marks_temporal_divergence_and_unresolved_transmission_without_rescoring_error():
    error = _error(
        suffix="shock",
        as_of="2026-08-12T10:00:00+00:00",
        value=-2.25,
        classification="DIRECTION_MISS",
    )
    view = ForecastErrorDiagnosticView(error, _context(error.error_id))

    html = render_forecast_error_track((view,))

    assert 'class="pg-error-context-divergent"' in html
    assert 'class="pg-error-context-unresolved"' in html
    assert "divergence 1" in html
    assert "uavklart transmisjon 1" in html
    assert "RATES_FX" in html
    assert "ikke kausalitet" in html
    assert "siste -2.25" in html
    assert error.normalized_center_error == -2.25


def test_track_without_context_keeps_clean_baseline_view():
    html = render_forecast_error_track(
        (_error(suffix="plain", as_of="2026-08-12T10:00:00+00:00", value=0.2),)
    )
    assert "pg-error-context-divergent" not in html
    assert "pg-error-context-unresolved" not in html
    assert "kontekst" not in html


def test_track_sorts_by_forecast_time_before_smoothing():
    errors = [
        _error(suffix="late", as_of="2026-08-12T12:00:00+00:00", value=2.0),
        _error(suffix="early", as_of="2026-08-12T10:00:00+00:00", value=-1.0),
        _error(suffix="middle", as_of="2026-08-12T11:00:00+00:00", value=0.0),
    ]
    html = render_forecast_error_track(errors, smoothing_window=3)
    assert html.index("2026-08-12T10:00:00+00:00") < html.index("2026-08-12T11:00:00+00:00")
    assert html.index("2026-08-12T11:00:00+00:00") < html.index("2026-08-12T12:00:00+00:00")


def test_empty_track_is_explicit_instead_of_inventing_accuracy():
    html = render_forecast_error_track([])
    assert "Venter på modne forecasts" in html
    assert "pg-error-median" not in html
