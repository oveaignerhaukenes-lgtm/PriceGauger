from autotrader_cadence_v2 import sleep_to_fixed_start_cadence_v2


def test_cadence_accepts_runtime_daemon_positional_call_style():
    sleeps: list[float] = []
    remaining = sleep_to_fixed_start_cadence_v2(
        100.0,
        15.0,
        monotonic=lambda: 104.0,
        sleep=sleeps.append,
    )
    assert remaining == 11.0
    assert sleeps == [11.0]


def test_cadence_keeps_keyword_call_style_backward_compatible():
    sleeps: list[float] = []
    remaining = sleep_to_fixed_start_cadence_v2(
        started_at=100.0,
        interval_seconds=2.0,
        monotonic=lambda: 101.5,
        sleep=sleeps.append,
    )
    assert remaining == 0.5
    assert sleeps == [0.5]
