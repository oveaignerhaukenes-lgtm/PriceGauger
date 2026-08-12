from datetime import datetime, timezone

from forecast_contracts import ForecastSnapshot
from forecast_timeline import _timeline_gaps, render_forecast_timeline_svg


def _forecast() -> ForecastSnapshot:
    return ForecastSnapshot(
        forecast_id="forecast:gap-polish",
        market="Gold",
        as_of="2026-08-09T22:00:00+00:00",
        reference_price=4400.0,
        direction="LONG_BIAS",
        direction_score=0.4,
        confidence=0.4,
        expected_move_low_pct=0.1,
        expected_move_high_pct=0.4,
        horizon_hours=4.0,
        time_scale="HOURS",
        decision_snapshot_id="decision:gap-polish",
        information_snapshot_id="information:gap-polish",
        market_snapshot_id="market:gap-polish",
        status="READY",
        missing_inputs=(),
        status_reason="test",
    )


def test_only_actual_weekend_closure_is_labeled_weekend_gap():
    friday = datetime(2026, 8, 7, 20, 59, tzinfo=timezone.utc)
    sunday_open = datetime(2026, 8, 9, 22, 0, tzinfo=timezone.utc)
    sunday_late = datetime(2026, 8, 9, 23, 0, tzinfo=timezone.utc)
    monday_late = datetime(2026, 8, 10, 8, 0, tzinfo=timezone.utc)

    gaps = _timeline_gaps(
        (
            (friday, 4380.0),
            (sunday_open, 4400.0),
            (sunday_late, 4402.0),
            (monday_late, 4405.0),
        )
    )

    assert [gap.label for gap in gaps] == ["WEEKEND GAP", "MARKET GAP"]


def test_narrow_gap_keeps_tooltip_without_cramped_typography():
    svg = render_forecast_timeline_svg(
        (_forecast(),),
        observed_prices=(
            ("2026-08-07T20:59:00+00:00", 4380.0),
            ("2026-08-09T22:00:00+00:00", 4400.0),
            ("2026-08-09T22:05:00+00:00", 4402.0),
        ),
        now=datetime(2026, 8, 9, 22, 5, tzinfo=timezone.utc),
    )

    assert "<title>WEEKEND GAP</title>" in svg
    assert ">WEEKEND</tspan>" not in svg
    assert ">GAP</tspan>" not in svg
    assert 'y="14"' in svg
    assert 'class="pg-price-axis"' in svg
    assert 'font-size:.64rem' in svg
    assert 'font-weight:400' in svg
