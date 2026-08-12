from __future__ import annotations

from datetime import datetime, timedelta, timezone

from forecast_contracts import ForecastSnapshot
from forecast_learning import _active_path
from forecast_timeline import _eligible, _horizon_label


AS_OF = datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc)


def _five_minute_forecast() -> ForecastSnapshot:
    return ForecastSnapshot(
        forecast_id="forecast:five-minute-test",
        market="Gold",
        as_of=AS_OF.isoformat(),
        reference_price=4400.0,
        direction="LONG_BIAS",
        direction_score=0.4,
        confidence=0.6,
        expected_move_low_pct=0.05,
        expected_move_high_pct=0.15,
        horizon_hours=5.0 / 60.0,
        time_scale="MINUTES",
        decision_snapshot_id="decision:five-minute-test",
        information_snapshot_id="information:five-minute-test",
        market_snapshot_id="market:five-minute-test",
        status="READY",
        missing_inputs=(),
        status_reason="test",
    )


def test_timeline_uses_exact_five_minute_end_instead_of_old_fifteen_minute_floor():
    eligible = _eligible(_five_minute_forecast())

    assert eligible is not None
    assert eligible.ends_at - eligible.as_of == timedelta(minutes=5)
    assert _horizon_label(5.0 / 60.0) == "5m"


def test_learning_completes_five_minute_outcome_after_five_active_minutes():
    forecast = _five_minute_forecast()
    points = [
        (AS_OF + timedelta(minutes=minute), 4400.0 + minute)
        for minute in range(1, 7)
    ]

    selected, progress, complete = _active_path(forecast, points)

    assert complete is True
    assert progress == 1.0
    assert selected[-1][0] == AS_OF + timedelta(minutes=5)
