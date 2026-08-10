from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from realtime_gap_repair import repair_recent_market_history
from realtime_market_data import RealtimeBar1m, RealtimeMarketDataStore
from saxo_provider import SaxoInstrument


class _ChartClient:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def chart(self, instrument, *, horizon_minutes, count, time, mode):
        self.calls.append(
            {
                "instrument": instrument,
                "horizon_minutes": horizon_minutes,
                "count": count,
                "time": time,
                "mode": mode,
            }
        )
        if not self.pages:
            return pd.DataFrame()
        return self.pages.pop(0)


def _frame(*minutes: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "timestamp": pd.Timestamp(stamp),
                "open": 80.0 + index,
                "high": 80.5 + index,
                "low": 79.5 + index,
                "close": 80.25 + index,
                "volume": 100.0 + index,
            }
            for index, stamp in enumerate(minutes)
        ]
    )


def test_repair_recent_history_pages_forward_and_fills_window(tmp_path):
    store = RealtimeMarketDataStore(tmp_path / "repair.db")
    instrument = SaxoInstrument(
        asset="Brent",
        uic=43660942,
        asset_type="ContractFutures",
        symbol="LCOV6",
    )
    client = _ChartClient(
        [
            _frame("2026-08-10T11:00:00Z", "2026-08-10T11:01:00Z"),
            _frame("2026-08-10T11:02:00Z", "2026-08-10T11:03:00Z"),
            pd.DataFrame(),
        ]
    )

    saved = repair_recent_market_history(
        store=store,
        client=client,
        market="Brent",
        instrument=instrument,
        now=datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc),
        lookback_hours=1,
        page_size=1200,
        max_pages=4,
    )

    assert saved == 4
    loaded = store.load_range(
        market="Brent",
        start="2026-08-10T10:59:00+00:00",
        end="2026-08-10T11:04:00+00:00",
    )
    assert [bar.bar_time for bar in loaded] == [
        "2026-08-10T11:00:00+00:00",
        "2026-08-10T11:01:00+00:00",
        "2026-08-10T11:02:00+00:00",
        "2026-08-10T11:03:00+00:00",
    ]
    assert len(client.calls) == 3
    assert all(call["mode"] == "From" for call in client.calls)
    assert all(call["horizon_minutes"] == 1 for call in client.calls)
    assert client.calls[1]["time"].isoformat() == "2026-08-10T11:02:00+00:00"


def test_repair_window_does_not_start_at_latest_bar_and_can_fill_older_holes(tmp_path):
    store = RealtimeMarketDataStore(tmp_path / "repair-old-hole.db")
    store.save_bar(
        RealtimeBar1m(
            market="Brent",
            bar_time="2026-08-10T11:50:00+00:00",
            open=88.0,
            high=88.1,
            low=87.9,
            close=88.0,
            sample_count=10,
            provider="Saxo OpenAPI",
            uic=43660942,
            asset_type="ContractFutures",
            symbol="LCOV6",
            volume=None,
        )
    )
    instrument = SaxoInstrument(
        asset="Brent",
        uic=43660942,
        asset_type="ContractFutures",
        symbol="LCOV6",
    )
    client = _ChartClient(
        [
            _frame("2026-08-10T11:00:00Z", "2026-08-10T11:01:00Z"),
            pd.DataFrame(),
        ]
    )

    repair_recent_market_history(
        store=store,
        client=client,
        market="Brent",
        instrument=instrument,
        now=datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc),
        lookback_hours=1,
    )

    loaded = store.load_range(
        market="Brent",
        start="2026-08-10T10:59:00+00:00",
        end="2026-08-10T11:51:00+00:00",
    )
    assert [bar.bar_time for bar in loaded] == [
        "2026-08-10T11:00:00+00:00",
        "2026-08-10T11:01:00+00:00",
        "2026-08-10T11:50:00+00:00",
    ]
