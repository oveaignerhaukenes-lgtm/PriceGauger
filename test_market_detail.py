from __future__ import annotations

from forecast_contracts import ForecastSnapshot
from market_detail import downsample_history, forecast_price_series, resolution_minutes


def _forecast(**overrides):
    values = dict(
        forecast_id="forecast:detail",
        market="Gold",
        as_of="2026-08-09T08:00:00+00:00",
        reference_price=4200.0,
        direction="LONG_BIAS",
        direction_score=0.6,
        confidence=0.65,
        expected_move_low_pct=0.5,
        expected_move_high_pct=1.5,
        horizon_hours=4.0,
        time_scale="HOURS",
        decision_snapshot_id="decision:detail",
        information_snapshot_id="information:detail",
        market_snapshot_id="market:detail",
        status="READY",
        missing_inputs=(),
        status_reason="test",
    )
    values.update(overrides)
    return ForecastSnapshot(**values)


def test_auto_resolution_scales_with_forecast_horizon():
    assert resolution_minutes("AUTO", horizon_hours=0.5) == 1
    assert resolution_minutes("AUTO", horizon_hours=4.0) == 5
    assert resolution_minutes("AUTO", horizon_hours=12.0) == 15
    assert resolution_minutes("AUTO", horizon_hours=48.0) == 60
    assert resolution_minutes("15m", horizon_hours=4.0) == 15
    assert resolution_minutes("1t", horizon_hours=4.0) == 60


def test_history_downsampling_keeps_latest_point_per_bucket():
    points = (
        ("2026-08-09T08:00:00+00:00", 100.0),
        ("2026-08-09T08:01:00+00:00", 101.0),
        ("2026-08-09T08:04:00+00:00", 104.0),
        ("2026-08-09T08:05:00+00:00", 105.0),
    )

    sampled = downsample_history(points, minutes=5)

    assert sampled == (
        ("2026-08-09T08:04:00+00:00", 104.0),
        ("2026-08-09T08:05:00+00:00", 105.0),
    )


def test_forecast_price_series_preserves_frozen_start_and_endpoint_prices():
    forecast = _forecast()
    series = forecast_price_series(forecast, steps=4)

    assert series.base[0] == ("2026-08-09T08:00:00+00:00", 4200.0)
    assert series.base[-1][0] == "2026-08-09T12:00:00+00:00"
    assert abs(series.bull[-1][1] - 4263.0) < 1e-9
    assert abs(series.bear[-1][1] - 4221.0) < 1e-9


def test_incomplete_forecast_does_not_generate_price_trajectory():
    series = forecast_price_series(_forecast(reference_price=None))

    assert series.base == ()
    assert series.fan_upper == ()
