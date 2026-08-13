from __future__ import annotations

from datetime import datetime, timedelta, timezone

from forecast_contracts import ForecastSnapshot
from forecast_shadow_sampling import sample_forecast_shadows


def _forecast(index: int, stamp: datetime) -> ForecastSnapshot:
    return ForecastSnapshot(
        forecast_id=f"forecast:{index}",
        market="Gold",
        as_of=stamp.isoformat(),
        reference_price=4200.0,
        direction="LONG_BIAS",
        direction_score=0.5,
        confidence=0.6,
        expected_move_low_pct=0.1,
        expected_move_high_pct=0.5,
        horizon_hours=1.0,
        time_scale="HOURS",
        decision_snapshot_id=f"decision:{index}",
        information_snapshot_id=f"information:{index}",
        market_snapshot_id=f"market:{index}",
        status="READY",
        missing_inputs=(),
        status_reason="test",
    )


def test_shadow_sampling_keeps_newest_snapshot_per_six_minute_bucket_and_active_latest():
    start = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)
    forecasts = tuple(_forecast(index, start + timedelta(minutes=index)) for index in range(13))
    sampled = sample_forecast_shadows(forecasts)
    assert [item.forecast_id for item in sampled] == ["forecast:5", "forecast:11", "forecast:12"]


def test_shadow_sampling_is_ten_historical_shadows_per_full_hour_when_data_is_dense():
    start = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)
    forecasts = tuple(_forecast(index, start + timedelta(minutes=index)) for index in range(61))
    sampled = sample_forecast_shadows(forecasts)
    assert len(sampled[:-1]) == 10
    assert sampled[-1].forecast_id == "forecast:60"


def test_shadow_sampling_does_not_synthesize_missing_forecasts():
    start = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)
    forecasts = (
        _forecast(0, start),
        _forecast(1, start + timedelta(minutes=20)),
        _forecast(2, start + timedelta(minutes=40)),
    )
    assert sample_forecast_shadows(forecasts) == forecasts
