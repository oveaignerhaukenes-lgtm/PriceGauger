from __future__ import annotations

from datetime import datetime, timezone

import pytest

from realtime_market_data import RealtimeBar1m
from trading_desk import TIMEFRAME_MINUTES, resample_bars
from trading_desk_clock import candle_countdown


def _bar(minute: str) -> RealtimeBar1m:
    return RealtimeBar1m(
        market="Gold",
        bar_time=minute,
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        sample_count=0,
        provider="Saxo OpenAPI",
        uic=1,
        asset_type="ContractFutures",
        symbol="GC",
        volume=10.0,
    )


def test_trading_desk_exposes_requested_intraday_timeframes() -> None:
    assert list(TIMEFRAME_MINUTES) == ["1m", "5m", "10m", "15m", "30m", "1h"]


@pytest.mark.parametrize(
    ("timeframe", "expected_stamp"),
    [
        ("10m", "2026-08-10T10:10:00+00:00"),
        ("30m", "2026-08-10T10:00:00+00:00"),
    ],
)
def test_added_timeframes_resample_on_canonical_utc_boundaries(
    timeframe: str,
    expected_stamp: str,
) -> None:
    result = resample_bars([_bar("2026-08-10T10:17:00Z")], timeframe=timeframe)

    assert len(result) == 1
    assert result[0].bar_time == expected_stamp


def test_countdown_tracks_next_five_minute_boundary() -> None:
    result = candle_countdown(
        datetime(2026, 8, 10, 10, 3, 42, 250000, tzinfo=timezone.utc),
        timeframe="5m",
    )

    assert result.seconds_remaining == 78
    assert result.label == "01:18"
    assert result.next_boundary.isoformat() == "2026-08-10T10:05:00+00:00"


def test_countdown_resets_to_full_interval_on_exact_boundary() -> None:
    result = candle_countdown("2026-08-10T10:30:00Z", timeframe="30m")

    assert result.seconds_remaining == 1800
    assert result.label == "30:00"
    assert result.next_boundary.isoformat() == "2026-08-10T11:00:00+00:00"
