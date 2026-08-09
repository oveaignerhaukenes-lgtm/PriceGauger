from datetime import datetime, timezone

from forecast_contracts import ForecastSnapshot
from forecast_timeline import render_forecast_timeline_svg


def _forecast(*, suffix: str, as_of: str, low: float, high: float) -> ForecastSnapshot:
    return ForecastSnapshot(
        forecast_id=f"forecast:{suffix}",
        market="Gold",
        as_of=as_of,
        reference_price=4200.0,
        direction="LONG_BIAS",
        direction_score=0.7,
        confidence=0.65,
        expected_move_low_pct=low,
        expected_move_high_pct=high,
        horizon_hours=4.0,
        time_scale="HOURS",
        decision_snapshot_id=f"decision:{suffix}",
        information_snapshot_id=f"information:{suffix}",
        market_snapshot_id=f"market:{suffix}",
        status="READY",
        missing_inputs=(),
        status_reason="test",
    )


def test_timeline_keeps_multiple_forecasts_and_actual_price():
    forecasts = (
        _forecast(suffix="a", as_of="2026-08-10T00:00:00+00:00", low=0.2, high=1.0),
        _forecast(suffix="b", as_of="2026-08-10T00:30:00+00:00", low=-0.1, high=0.8),
    )
    observed = (
        ("2026-08-09T23:30:00+00:00", 4190.0),
        ("2026-08-10T00:00:00+00:00", 4200.0),
        ("2026-08-10T00:20:00+00:00", 4210.0),
        ("2026-08-10T00:40:00+00:00", 4205.0),
    )

    svg = render_forecast_timeline_svg(
        forecasts,
        observed_prices=observed,
        now=datetime(2026, 8, 10, 0, 40, tzinfo=timezone.utc),
    )

    assert "2 SNAPSHOTS" in svg
    assert svg.count("pg-forecast-fan") == 2
    assert svg.count("pg-forecast-base") == 2
    assert "pg-realized" in svg
    assert "svart = faktisk pris" in svg


def test_timeline_has_taller_plot_and_right_price_scale():
    forecast = _forecast(
        suffix="axis",
        as_of="2026-08-10T00:00:00+00:00",
        low=-0.2,
        high=0.4,
    )

    svg = render_forecast_timeline_svg(
        (forecast,),
        observed_prices=(("2026-08-10T00:05:00+00:00", 4205.0),),
    )

    assert 'style="height:13.5rem"' in svg
    assert "høyre = pris" in svg
    assert 'x1="90"' in svg
    assert "4200" in svg


def test_timeline_limits_old_layers_but_keeps_newest():
    forecasts = tuple(
        _forecast(
            suffix=str(index),
            as_of=f"2026-08-10T0{index}:00:00+00:00",
            low=0.1 * index,
            high=0.5 + 0.1 * index,
        )
        for index in range(5)
    )

    svg = render_forecast_timeline_svg(forecasts, max_layers=4)

    assert "4 SNAPSHOTS" in svg
    assert svg.count("pg-forecast-fan") == 4
    assert svg.count("pg-forecast-base") == 4


def test_incomplete_forecast_is_not_drawn_as_complete_layer():
    complete = _forecast(
        suffix="ok",
        as_of="2026-08-10T00:00:00+00:00",
        low=0.2,
        high=1.0,
    )
    incomplete = ForecastSnapshot(
        forecast_id="forecast:bad",
        market="Gold",
        as_of="2026-08-10T00:30:00+00:00",
        reference_price=4200.0,
        direction="LONG_BIAS",
        direction_score=0.7,
        confidence=0.65,
        expected_move_low_pct=None,
        expected_move_high_pct=None,
        horizon_hours=4.0,
        time_scale="HOURS",
        decision_snapshot_id="decision:bad",
        information_snapshot_id="information:bad",
        market_snapshot_id="market:bad",
        status="DEGRADED",
        missing_inputs=("expected_move_interval",),
        status_reason="test",
    )

    svg = render_forecast_timeline_svg((complete, incomplete))

    assert "1 SNAPSHOT" in svg
    assert svg.count("pg-forecast-fan") == 1
