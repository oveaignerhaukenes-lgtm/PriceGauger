from datetime import datetime, timezone

from forecast_contracts import ForecastSnapshot
from forecast_timeline import render_forecast_timeline_svg


def _forecast(index: int) -> ForecastSnapshot:
    return ForecastSnapshot(
        forecast_id=f"forecast:markdown-safe:{index}",
        market="Gold",
        as_of=f"2026-08-10T0{index}:00:00+00:00",
        reference_price=4400.0 + index,
        direction="LONG_BIAS",
        direction_score=0.4,
        confidence=0.4,
        expected_move_low_pct=0.1,
        expected_move_high_pct=0.4,
        horizon_hours=4.0,
        time_scale="HOURS",
        decision_snapshot_id=f"decision:{index}",
        information_snapshot_id=f"information:{index}",
        market_snapshot_id=f"market:{index}",
        status="READY",
        missing_inputs=(),
        status_reason="test",
    )


def test_forecast_fragment_is_single_line_for_streamlit_markdown() -> None:
    html = render_forecast_timeline_svg(
        tuple(_forecast(index) for index in range(1, 9)),
        observed_prices=(
            ("2026-08-10T01:00:00+00:00", 4401.0),
            ("2026-08-10T08:30:00+00:00", 4410.0),
        ),
        now=datetime(2026, 8, 10, 8, 30, tzinfo=timezone.utc),
    )

    assert "\n" not in html
    assert '<svg class="pg-forecast-svg"' in html
    assert "<polyline" in html
    assert "</svg>" in html
