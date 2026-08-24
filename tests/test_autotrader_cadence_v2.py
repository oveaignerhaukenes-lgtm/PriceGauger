from __future__ import annotations

from autotrader_cadence_v2 import sleep_to_fixed_start_cadence_v2


def test_fixed_start_cadence_subtracts_cycle_duration() -> None:
    sleeps: list[float] = []
    remaining = sleep_to_fixed_start_cadence_v2(
        started_at=100.0,
        interval_seconds=2.0,
        monotonic=lambda: 100.75,
        sleep=sleeps.append,
    )
    assert remaining == 1.25
    assert sleeps == [1.25]


def test_fixed_start_cadence_uses_bounded_backoff_after_overrun() -> None:
    sleeps: list[float] = []
    remaining = sleep_to_fixed_start_cadence_v2(
        started_at=100.0,
        interval_seconds=2.0,
        monotonic=lambda: 102.5,
        sleep=sleeps.append,
    )
    assert remaining == 1.0
    assert sleeps == [1.0]
