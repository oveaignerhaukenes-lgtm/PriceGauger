from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from external_market_read_v2 import ExternalMarketReadServiceV2


def _bar(minute: int, *, close: float, high: float | None = None, low: float | None = None, volume: float = 1.0):
    return SimpleNamespace(
        instrument_id=10,
        market_id=20,
        market_name="Gold",
        bar_time=f"2026-08-26T21:{minute:02d}:00+00:00",
        open=close - 0.5,
        high=close + 0.5 if high is None else high,
        low=close - 1.0 if low is None else low,
        close=close,
        volume=volume,
        quality_flags=1,
    )


class _FakeStore:
    def __init__(self, bars):
        self.bars = list(bars)

    def load_latest(self, *, market: str):
        return self.bars[-1] if market == "Gold" and self.bars else None

    def load_range(self, *, market: str, start, end, limit: int):
        if market != "Gold":
            return ()
        return tuple(self.bars[:limit])


def _service(bars):
    service = ExternalMarketReadServiceV2(
        "unused.db",
        stale_after_seconds=180,
        now_fn=lambda: datetime(2026, 8, 26, 21, 5, tzinfo=timezone.utc),
    )
    service.store = _FakeStore(bars)
    return service


def test_snapshot_exposes_freshness_and_no_execution_capability():
    result = _service([_bar(4, close=4400.0)]).snapshot("Gold")

    assert result["market"] == "Gold"
    assert result["close"] == 4400.0
    assert result["age_seconds"] == 60.0
    assert result["stale"] is False
    assert result["source"] == "pricegauger_canonical_v2"
    assert result["execution_capability"] is False


def test_snapshot_marks_old_data_stale():
    result = _service([_bar(1, close=4398.0)]).snapshot("Gold")
    assert result["stale"] is True


def test_candles_aggregate_canonical_one_minute_bars():
    service = _service(
        [
            _bar(0, close=100.0, high=101.0, low=99.0, volume=2.0),
            _bar(1, close=102.0, high=103.0, low=100.0, volume=3.0),
            _bar(4, close=101.0, high=104.0, low=98.0, volume=4.0),
            _bar(5, close=105.0, high=106.0, low=104.0, volume=5.0),
        ]
    )

    result = service.candles("Gold", horizon_minutes=5, count=10)

    assert result["execution_capability"] is False
    assert result["horizon_minutes"] == 5
    assert result["count"] == 2
    first, second = result["candles"]
    assert first["time"] == "2026-08-26T21:00:00+00:00"
    assert first["open"] == 99.5
    assert first["high"] == 104.0
    assert first["low"] == 98.0
    assert first["close"] == 101.0
    assert first["volume"] == 9.0
    assert second["time"] == "2026-08-26T21:05:00+00:00"
    assert second["close"] == 105.0


def test_candles_reject_unsupported_horizon():
    with pytest.raises(ValueError, match="horizon_minutes"):
        _service([_bar(4, close=100.0)]).candles("Gold", horizon_minutes=7)


def test_snapshot_rejects_missing_market():
    with pytest.raises(ValueError, match="market is required"):
        _service([]).snapshot("  ")


def test_public_read_service_has_no_order_methods():
    service = _service([])
    forbidden = {"place_order", "amend_order", "cancel_order", "close_position", "execute"}
    assert forbidden.isdisjoint(set(dir(service)))
