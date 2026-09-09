from __future__ import annotations

from datetime import datetime, timedelta, timezone

from hypervigilant_macd_v1 import bucket_start_v1, materialize_hypervigilant_macd_v1


def _points(count: int = 160) -> tuple[tuple[str, float], ...]:
    start = datetime(2026, 9, 9, 6, 0, tzinfo=timezone.utc)
    result = []
    for index in range(count):
        # Enough shape to warm EMA while avoiding a perfectly flat zero-spread series.
        price = 29500.0 + (index * 0.35) + ((index % 11) - 5) * 0.8
        result.append(((start + timedelta(minutes=index)).isoformat(), price))
    return tuple(result)


def test_bucket_start_is_epoch_aligned() -> None:
    stamp = datetime(2026, 9, 9, 8, 17, 43, tzinfo=timezone.utc)
    assert bucket_start_v1(stamp, timeframe_minutes=2).minute == 16
    assert bucket_start_v1(stamp, timeframe_minutes=5).minute == 15
    assert bucket_start_v1(stamp, timeframe_minutes=15).minute == 15
    assert bucket_start_v1(stamp, timeframe_minutes=30).minute == 0


def test_forming_price_replaces_provisional_period_without_adding_a_macd_period() -> None:
    points = _points()
    forming_time = datetime(2026, 9, 9, 8, 40, tzinfo=timezone.utc)
    low = materialize_hypervigilant_macd_v1(
        points,
        market="US Tech",
        timeframe_minutes=2,
        forming_bar_time=forming_time,
        forming_close=29420.0,
    )
    high = materialize_hypervigilant_macd_v1(
        points,
        market="US Tech",
        timeframe_minutes=2,
        forming_bar_time=forming_time,
        forming_close=29720.0,
    )

    assert len(low) == len(high)
    assert low[-1].bar_time == high[-1].bar_time
    assert low[-1].spread != high[-1].spread


def test_same_materializer_supports_slow_hypervigilant_timeframes() -> None:
    points = _points(300)
    forming_time = datetime(2026, 9, 9, 11, 1, tzinfo=timezone.utc)
    for minutes in (1, 2, 5, 15, 30):
        observations = materialize_hypervigilant_macd_v1(
            points,
            market="US Tech",
            timeframe_minutes=minutes,
            forming_bar_time=forming_time,
            forming_close=29600.0,
        )
        assert observations
        assert observations[-1].timeframe_minutes == minutes
