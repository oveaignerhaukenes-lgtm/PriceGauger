from datetime import datetime, timedelta, timezone

from forecast_contracts import ForecastSnapshot
from forecast_timeline import (
    _history_evaluation_strength,
    _observed_price_at,
    render_forecast_timeline_svg,
)


def _forecast(*, suffix: str, as_of: datetime, low: float = 0.2, high: float = 0.8) -> ForecastSnapshot:
    return ForecastSnapshot(
        forecast_id=f"forecast:{suffix}",
        market="Gold",
        as_of=as_of.isoformat(),
        reference_price=4200.0,
        direction="LONG_BIAS",
        direction_score=0.6,
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


def test_observed_price_interpolates_only_across_continuous_canonical_history():
    start = datetime(2026, 8, 10, 0, 0, tzinfo=timezone.utc)
    continuous = ((start, 100.0), (start + timedelta(minutes=2), 102.0))
    assert _observed_price_at(continuous, start + timedelta(minutes=1)) == 101.0

    gapped = ((start, 100.0), (start + timedelta(minutes=10), 110.0))
    assert _observed_price_at(gapped, start + timedelta(minutes=5)) is None


def test_history_evaluation_fades_in_only_in_older_half_of_history():
    assert _history_evaluation_strength(64.0, split_x=64.0) == 0.0
    assert _history_evaluation_strength(40.0, split_x=64.0) == 0.0
    assert 0.0 < _history_evaluation_strength(20.0, split_x=64.0) < 1.0
    assert _history_evaluation_strength(0.0, split_x=64.0) == 1.0


def test_elapsed_forecasts_turn_into_measured_error_while_future_remains_forecast():
    start = datetime(2026, 8, 10, 0, 0, tzinfo=timezone.utc)
    forecasts = (
        _forecast(suffix="old", as_of=start),
        _forecast(suffix="latest", as_of=start + timedelta(hours=6), low=-0.1, high=0.6),
    )
    observed = tuple(
        ((start + timedelta(minutes=20 * index)).isoformat(), 4200.0 + index)
        for index in range(22)
    )
    svg = render_forecast_timeline_svg(
        forecasts,
        observed_prices=observed,
        now=start + timedelta(hours=7),
        steps=12,
    )

    assert "HISTORIKK · FASIT" in svg
    assert "NÅ → PROGNOSE" in svg
    assert "pg-now-boundary" in svg
    assert "pg-forecast-error" in svg
    assert "EVALUERT" in svg
    assert "gamle prognoser fader til målt avvik" in svg
