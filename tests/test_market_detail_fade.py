from datetime import datetime, timedelta, timezone

import pytest

from market_detail import fade_path_segments, ghost_forecast_opacities


def test_ghost_forecast_opacities_strengthen_from_oldest_to_newest() -> None:
    values = ghost_forecast_opacities(4)

    assert len(values) == 4
    assert values[0] == pytest.approx(0.08)
    assert values[-1] == pytest.approx(0.34)
    assert list(values) == sorted(values)


def test_fade_path_segments_strengthen_toward_right_edge() -> None:
    start = datetime(2026, 8, 10, 0, 0, tzinfo=timezone.utc)
    points = tuple((start + timedelta(minutes=index), 100.0 + index) for index in range(5))

    segments = fade_path_segments(points, peak_opacity=0.4)

    assert len(segments) == 4
    assert segments[0][0] == (points[0], points[1])
    assert segments[-1][0] == (points[-2], points[-1])
    opacities = [opacity for _, opacity in segments]
    assert opacities == sorted(opacities)
    assert opacities[0] < 0.4
    assert opacities[-1] == pytest.approx(0.4)


def test_fade_path_segments_need_two_points() -> None:
    now = datetime(2026, 8, 10, tzinfo=timezone.utc)
    assert fade_path_segments(((now, 100.0),), peak_opacity=0.3) == ()
