from __future__ import annotations

import pytest

from realtime_market_data import RealtimeBar1m
from trading_desk import canonical_chart_bars, normalized_close_series, resample_bars


def _bar(
    minute: str,
    *,
    market: str = "Gold",
    open_price: float = 100.0,
    high: float = 101.0,
    low: float = 99.0,
    close: float = 100.5,
    volume: float | None = 10.0,
) -> RealtimeBar1m:
    return RealtimeBar1m(
        market=market,
        bar_time=minute,
        open=open_price,
        high=high,
        low=low,
        close=close,
        sample_count=0,
        provider="Saxo OpenAPI",
        uic=1,
        asset_type="ContractFutures",
        symbol="GC",
        volume=volume,
    )


def test_resample_five_minutes_preserves_ohlc_and_sums_true_volume() -> None:
    bars = [
        _bar("2026-08-09T10:00:00Z", open_price=100, high=102, low=99, close=101, volume=10),
        _bar("2026-08-09T10:01:00Z", open_price=101, high=104, low=100, close=103, volume=20),
        _bar("2026-08-09T10:02:00Z", open_price=103, high=103.5, low=98, close=99, volume=30),
        _bar("2026-08-09T10:03:00Z", open_price=99, high=101, low=97, close=100, volume=40),
        _bar("2026-08-09T10:04:00Z", open_price=100, high=105, low=99, close=104, volume=50),
    ]

    result = resample_bars(reversed(bars), timeframe="5m")

    assert len(result) == 1
    assert result[0].bar_time == "2026-08-09T10:00:00+00:00"
    assert (result[0].open, result[0].high, result[0].low, result[0].close) == (100, 105, 97, 104)
    assert result[0].volume == 150


@pytest.mark.parametrize(
    ("timeframe", "expected_stamp"),
    [
        ("15m", "2026-08-09T10:00:00+00:00"),
        ("1h", "2026-08-09T10:00:00+00:00"),
    ],
)
def test_resample_supported_higher_timeframes(timeframe: str, expected_stamp: str) -> None:
    result = resample_bars(
        [
            _bar("2026-08-09T10:07:00Z", close=101),
            _bar("2026-08-09T10:12:00Z", open_price=101, high=103, low=100, close=102),
        ],
        timeframe=timeframe,
    )

    assert len(result) == 1
    assert result[0].bar_time == expected_stamp
    assert result[0].close == 102
    assert result[0].volume is None


def test_missing_minutes_are_not_fabricated_and_make_volume_unknown() -> None:
    result = resample_bars(
        [
            _bar("2026-08-09T10:00:00Z", volume=10),
            _bar("2026-08-09T10:04:00Z", volume=20),
            _bar("2026-08-09T10:10:00Z", volume=30),
        ],
        timeframe="5m",
    )

    assert [item.bar_time for item in result] == [
        "2026-08-09T10:00:00+00:00",
        "2026-08-09T10:10:00+00:00",
    ]
    assert result[0].volume is None
    assert result[1].volume is None


def test_resampled_volume_is_unknown_when_any_constituent_bar_lacks_true_volume() -> None:
    result = resample_bars(
        [
            _bar("2026-08-09T10:00:00Z", volume=10),
            _bar("2026-08-09T10:01:00Z", volume=None),
            _bar("2026-08-09T10:02:00Z", volume=30),
            _bar("2026-08-09T10:03:00Z", volume=40),
            _bar("2026-08-09T10:04:00Z", volume=50),
        ],
        timeframe="5m",
    )

    assert result[0].volume is None


def test_offset_timestamps_bucket_on_canonical_utc_axis() -> None:
    result = resample_bars(
        [_bar("2026-08-09T12:04:00+02:00")],
        timeframe="5m",
    )

    assert result[0].bar_time == "2026-08-09T10:00:00+00:00"


def test_exact_duplicate_bar_is_deduplicated() -> None:
    bar = _bar("2026-08-09T10:00:00Z")

    assert canonical_chart_bars([bar, bar]) == canonical_chart_bars([bar])


def test_conflicting_duplicate_bar_is_rejected() -> None:
    with pytest.raises(ValueError, match="Conflicting duplicate"):
        canonical_chart_bars(
            [
                _bar("2026-08-09T10:00:00Z", close=100.5),
                _bar("2026-08-09T10:00:00Z", close=100.6),
            ]
        )


def test_normalized_series_starts_at_100_and_preserves_relative_move() -> None:
    points = normalized_close_series(
        [
            _bar("2026-08-09T10:00:00Z", open_price=50, high=51, low=49, close=50),
            _bar("2026-08-09T10:01:00Z", open_price=50, high=56, low=49, close=55),
        ]
    )

    assert points[0][1] == 100.0
    assert points[1][1] == pytest.approx(110.0)


def test_empty_series_remains_empty() -> None:
    assert resample_bars([], timeframe="5m") == ()
    assert normalized_close_series([]) == ()
