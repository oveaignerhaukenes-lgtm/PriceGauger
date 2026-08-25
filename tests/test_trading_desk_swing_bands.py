from datetime import datetime, timedelta, timezone

from trading_desk import ChartBar
from trading_desk_swing_bands import derive_swing_bands


def _bars(values):
    start = datetime(2026, 8, 25, 10, 0, tzinfo=timezone.utc)
    result = []
    previous = float(values[0])
    for index, close in enumerate(values):
        close = float(close)
        high = max(previous, close) + 0.2
        low = min(previous, close) - 0.2
        result.append(
            ChartBar(
                market="Gold",
                bar_time=start + timedelta(minutes=index),
                open=previous,
                high=high,
                low=low,
                close=close,
                volume=1.0,
            )
        )
        previous = close
    return tuple(result)


def test_swing_bands_return_confirmed_low_and_high_zones_around_current_price():
    bars = _bars([100, 101, 103, 101, 99, 97, 99, 102, 104, 102, 100])
    bands = derive_swing_bands(bars, pivot_radius=2)

    kinds = {item.kind for item in bands}
    assert kinds == {"LOW", "HIGH"}
    for band in bands:
        assert band.lower < band.pivot_price < band.upper


def test_unconfirmed_edge_is_not_used_as_swing_pivot():
    bars = _bars([100, 101, 102, 101, 100, 99, 98, 97])
    bands = derive_swing_bands(bars, pivot_radius=2)

    assert all(item.pivot_time != bars[-1].bar_time for item in bands)
