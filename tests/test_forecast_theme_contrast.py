from forecast_contracts import ForecastSnapshot
from forecast_timeline import render_forecast_timeline_svg


def _forecast() -> ForecastSnapshot:
    return ForecastSnapshot(
        forecast_id="forecast:theme",
        market="Gold",
        as_of="2026-08-11T06:00:00+00:00",
        reference_price=4200.0,
        direction="LONG_BIAS",
        direction_score=0.4,
        confidence=0.4,
        expected_move_low_pct=0.1,
        expected_move_high_pct=0.4,
        horizon_hours=4.0,
        time_scale="HOURS",
        decision_snapshot_id="decision:theme",
        information_snapshot_id="information:theme",
        market_snapshot_id="market:theme",
        status="READY",
        missing_inputs=(),
        status_reason="test",
    )


def test_realized_price_uses_theme_contrast_and_no_stretched_markers() -> None:
    svg = render_forecast_timeline_svg(
        (_forecast(),),
        observed_prices=(
            ("2026-08-11T06:00:00+00:00", 4200.0),
            ("2026-08-11T06:10:00+00:00", 4198.0),
        ),
    )

    assert 'class="pg-realized"' in svg
    assert "stroke:currentColor" in svg
    assert "<circle" not in svg
    assert "terminalfeil måles i modellfeilsporet" in svg
    assert "pg-forecast-error" not in svg
