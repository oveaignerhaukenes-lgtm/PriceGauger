from adaptation_diagnostics import ForecastAdaptationContext, ForecastErrorDiagnosticView
from adaptation_statistics import summarize_adaptation_diagnostics
from forecast_error import ForecastErrorObservation


def _error(index: int, value: float) -> ForecastErrorObservation:
    return ForecastErrorObservation(
        error_id=f"error:{index}",
        forecast_id=f"forecast:{index}",
        market="Silver",
        horizon_hours=1.0,
        forecast_as_of=f"2026-08-12T{index:02d}:00:00+00:00",
        outcome_evaluated_at=f"2026-08-12T{index:02d}:59:00+00:00",
        expected_low_pct=-0.5,
        expected_high_pct=0.5,
        expected_center_pct=0.0,
        expected_half_width_pct=0.5,
        realized_move_pct=value * 0.5,
        signed_center_error_pct=value * 0.5,
        normalized_center_error=value,
        signed_interval_error_pct=0.0,
        normalized_interval_error=0.0,
        interval_hit=abs(value) <= 1.0,
        direction_hit=True,
        classification="IN_INTERVAL" if abs(value) <= 1.0 else "DIRECTION_ONLY",
    )


def _context(error_id: str, *, divergent: bool, unresolved: bool) -> ForecastAdaptationContext:
    return ForecastAdaptationContext(
        error_id=error_id,
        response_count=1,
        divergent_count=1 if divergent else 0,
        aligned_count=0 if divergent else 1,
        unconfirmed_count=0,
        transmission_count=1,
        resolved_count=0 if unresolved else 1,
        unresolved_count=1 if unresolved else 0,
        dominant_channels=() if unresolved else ("RATES_FX",),
    )


def _view(index: int, value: float, *, divergent: bool, unresolved: bool) -> ForecastErrorDiagnosticView:
    error = _error(index, value)
    return ForecastErrorDiagnosticView(
        error,
        _context(error.error_id, divergent=divergent, unresolved=unresolved),
    )


def test_summary_requires_minimum_samples_before_exposing_group_delta():
    views = [
        _view(1, 2.0, divergent=True, unresolved=True),
        _view(2, 0.2, divergent=False, unresolved=False),
    ]

    summary = summarize_adaptation_diagnostics(views)

    assert summary.divergence_comparison_ready is False
    assert summary.transmission_comparison_ready is False
    assert summary.divergence_error_delta is None
    assert summary.transmission_error_delta is None


def test_summary_compares_absolute_error_without_directional_cancellation():
    views = []
    for index, value in enumerate((2.0, -2.4, 1.8, -2.2, 2.1), start=1):
        views.append(_view(index, value, divergent=True, unresolved=True))
    for index, value in enumerate((0.2, -0.4, 0.3, -0.1, 0.5), start=6):
        views.append(_view(index, value, divergent=False, unresolved=False))

    summary = summarize_adaptation_diagnostics(views)

    assert summary.divergence_comparison_ready is True
    assert summary.transmission_comparison_ready is True
    assert summary.median_abs_error_divergence == 2.1
    assert summary.median_abs_error_nondivergence == 0.3
    assert summary.divergence_error_delta == 1.8
    assert summary.median_abs_error_unresolved == 2.1
    assert summary.median_abs_error_resolved == 0.3
    assert summary.transmission_error_delta == 1.8


def test_context_free_errors_contribute_only_to_overall_error():
    plain = _error(1, -1.25)

    summary = summarize_adaptation_diagnostics((plain,))

    assert summary.total_count == 1
    assert summary.context_count == 0
    assert summary.median_abs_error_all == 1.25
    assert summary.divergence_count == 0
