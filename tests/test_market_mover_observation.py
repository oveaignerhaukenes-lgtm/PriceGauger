from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from market_mover_observation import format_elapsed, observe_market_mover


class StubHistoryStore:
    def __init__(self, points):
        self.points = tuple(points)
        self.calls = []

    def load_range(self, **kwargs):
        self.calls.append(kwargs)
        return self.points


def _alert(direction="UP", horizon_hours=4.0):
    return SimpleNamespace(
        created_at="2026-08-09T08:00:00+00:00",
        market="Brent",
        expected_direction=direction,
        horizon_hours=horizon_hours,
    )


def test_up_alert_selects_strongest_positive_excursion_and_peak_time():
    store = StubHistoryStore(
        (
            ("2026-08-09T08:00:00+00:00", 100.0),
            ("2026-08-09T08:20:00+00:00", 100.5),
            ("2026-08-09T08:50:00+00:00", 101.2),
            ("2026-08-09T09:20:00+00:00", 100.8),
        )
    )
    result = observe_market_mover(
        _alert("UP"),
        store,
        now=datetime(2026, 8, 9, 10, 0, tzinfo=timezone.utc),
    )
    assert result is not None
    assert result.move_pct == pytest.approx(1.2)
    assert result.elapsed_minutes == 50
    assert result.peak_price == 101.2
    assert result.observation_complete is False


def test_down_alert_selects_strongest_negative_excursion():
    store = StubHistoryStore(
        (
            ("2026-08-09T08:00:00+00:00", 100.0),
            ("2026-08-09T08:15:00+00:00", 99.5),
            ("2026-08-09T08:45:00+00:00", 98.4),
            ("2026-08-09T09:00:00+00:00", 99.0),
        )
    )
    result = observe_market_mover(
        _alert("DOWN", horizon_hours=1.0),
        store,
        now=datetime(2026, 8, 9, 10, 0, tzinfo=timezone.utc),
    )
    assert result is not None
    assert result.move_pct == pytest.approx(-1.6)
    assert result.elapsed_minutes == 45
    assert result.observation_complete is True


def test_uncertain_alert_uses_largest_absolute_move():
    store = StubHistoryStore(
        (
            ("2026-08-09T08:00:00+00:00", 100.0),
            ("2026-08-09T08:10:00+00:00", 101.0),
            ("2026-08-09T08:30:00+00:00", 97.5),
        )
    )
    result = observe_market_mover(
        _alert("UNCERTAIN"),
        store,
        now=datetime(2026, 8, 9, 9, 0, tzinfo=timezone.utc),
    )
    assert result is not None
    assert result.move_pct == pytest.approx(-2.5)
    assert result.elapsed_minutes == 30


def test_observation_requires_two_real_prices():
    store = StubHistoryStore((("2026-08-09T08:00:00+00:00", 100.0),))
    assert observe_market_mover(
        _alert(),
        store,
        now=datetime(2026, 8, 9, 9, 0, tzinfo=timezone.utc),
    ) is None


def test_elapsed_format_tracks_scale():
    assert format_elapsed(50) == "50 min"
    assert format_elapsed(120) == "2 t"
    assert format_elapsed(135) == "2 t 15 min"
    assert format_elapsed(1620) == "1 d 3 t"
