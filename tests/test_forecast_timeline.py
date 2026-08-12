from datetime import datetime, timedelta, timezone

from forecast_contracts import ForecastSnapshot
from forecast_timeline import _display_seconds, _shape, _timeline_gaps, render_forecast_timeline_svg


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

    assert "2 SYNLIGE" in svg
    assert svg.count("pg-forecast-fan") == 2
    assert svg.count("pg-forecast-base") == 2
    assert "pg-realized" in svg
    assert "kontrastlinje = faktisk pris" in svg


def test_timeline_has_normal_html_right_price_scale():
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

    assert 'style="height:13.5rem' in svg
    assert "høyre = pris" in svg
    assert 'x1="90"' in svg
    assert 'class="pg-price-axis"' in svg
    assert "font-size:.64rem" in svg
    assert "font-weight:400" in svg
    assert "4200" in svg


def test_default_trend_shape_is_linear_without_invented_knee():
    assert _shape(0.25, 1.0, "TREND") == 0.25
    assert _shape(0.50, 1.0, "TREND") == 0.50
    assert _shape(0.75, 1.0, "TREND") == 0.75


def test_weekend_gap_is_compressed_and_actual_price_is_not_connected_across_it():
    friday_a = datetime(2026, 8, 7, 20, 58, tzinfo=timezone.utc)
    friday_b = datetime(2026, 8, 7, 20, 59, tzinfo=timezone.utc)
    sunday_a = datetime(2026, 8, 9, 22, 0, tzinfo=timezone.utc)
    sunday_b = datetime(2026, 8, 9, 22, 1, tzinfo=timezone.utc)
    observed_dt = (
        (friday_a, 4198.0),
        (friday_b, 4200.0),
        (sunday_a, 4220.0),
        (sunday_b, 4222.0),
    )
    gaps = _timeline_gaps(observed_dt)

    assert len(gaps) == 1
    assert gaps[0].label == "WEEKEND GAP"
    assert _display_seconds(sunday_a, axis_start=friday_a, gaps=gaps) < 20 * 60

    forecast = _forecast(
        suffix="weekend",
        as_of="2026-08-09T22:00:00+00:00",
        low=-0.2,
        high=0.4,
    )
    svg = render_forecast_timeline_svg(
        (forecast,),
        observed_prices=tuple((stamp.isoformat(), price) for stamp, price in observed_dt),
        now=sunday_b,
    )

    assert "<title>WEEKEND GAP</title>" in svg
    assert svg.count('class="pg-realized"') == 2


def test_narrow_compressed_gap_does_not_render_cramped_ufo_label():
    forecast = _forecast(
        suffix="gap",
        as_of="2026-08-10T08:00:00+00:00",
        low=-0.2,
        high=0.4,
    )
    observed = (
        ("2026-08-10T00:00:00+00:00", 4200.0),
        ("2026-08-10T00:01:00+00:00", 4201.0),
        ("2026-08-10T08:00:00+00:00", 4210.0),
        ("2026-08-10T08:01:00+00:00", 4211.0),
    )

    svg = render_forecast_timeline_svg((forecast,), observed_prices=observed)

    assert "<title>MARKET GAP</title>" in svg
    assert ">MARKET</tspan>" not in svg
    assert ">GAP</tspan>" not in svg


def test_large_non_weekend_data_gap_is_labeled_market_gap():
    observed = (
        (datetime(2026, 8, 10, 0, 0, tzinfo=timezone.utc), 4200.0),
        (datetime(2026, 8, 10, 8, 0, tzinfo=timezone.utc), 4210.0),
    )

    gaps = _timeline_gaps(observed)

    assert len(gaps) == 1
    assert gaps[0].label == "MARKET GAP"


def test_timeline_default_keeps_all_forecasts_that_overlap_viewport():
    start = datetime(2026, 8, 10, 0, 0, tzinfo=timezone.utc)
    forecasts = tuple(
        _forecast(
            suffix=str(index),
            as_of=(start + timedelta(minutes=15 * index)).isoformat(),
            low=0.1 + 0.01 * index,
            high=0.5 + 0.01 * index,
        )
        for index in range(14)
    )

    svg = render_forecast_timeline_svg(forecasts)

    assert "14 SYNLIGE" in svg
    assert svg.count("pg-forecast-fan") == 14
    assert svg.count("pg-forecast-base") == 14


def test_timeline_explicit_layer_limit_still_keeps_newest():
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

    assert "4 SYNLIGE" in svg
    assert svg.count("pg-forecast-fan") == 4
    assert svg.count("pg-forecast-base") == 4


def test_forecast_layer_is_removed_only_after_its_horizon_rolls_left():
    forecasts = (
        _forecast(suffix="expired", as_of="2026-08-09T23:00:00+00:00", low=0.1, high=0.5),
        _forecast(suffix="edge", as_of="2026-08-10T00:00:00+00:00", low=0.1, high=0.5),
        _forecast(suffix="latest", as_of="2026-08-10T08:00:00+00:00", low=0.1, high=0.5),
    )
    observed = (
        ("2026-08-10T11:59:00+00:00", 4210.0),
        ("2026-08-10T12:00:00+00:00", 4211.0),
    )

    svg = render_forecast_timeline_svg(forecasts, observed_prices=observed)

    # Latest 4h forecast ends at 12:00, so the rolling two-horizon viewport starts
    # at 04:00. The 00:00 forecast ends exactly at 04:00 and remains visible; the
    # 23:00 forecast ended at 03:00 and has physically rolled out.
    assert "2 SYNLIGE" in svg
    assert svg.count("pg-forecast-fan") == 2
    assert svg.count("pg-forecast-base") == 2


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

    assert "1 SYNLIGE" in svg
    assert svg.count("pg-forecast-fan") == 1
