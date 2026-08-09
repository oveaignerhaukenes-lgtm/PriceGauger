from __future__ import annotations

import pandas as pd

from realtime_market_data import RealtimeMarketDataStore
from saxo_provider import SIM_BASE_URL, SaxoClient, SaxoInstrument
from saxo_streaming import BACKFILL_TIMEOUT_SECONDS, _backfill_client, bars_from_chart_frame


def test_chart_backfill_keeps_only_completed_minutes_and_preserves_ohlcv():
    instrument = SaxoInstrument(
        asset="Gold",
        uic=123,
        asset_type="ContractFutures",
        symbol="GCQ6",
    )
    frame = pd.DataFrame(
        [
            {
                "timestamp": pd.Timestamp("2026-08-09T10:28:00Z"),
                "open": 100.0,
                "high": 103.0,
                "low": 99.0,
                "close": 102.0,
                "volume": 120.0,
            },
            {
                "timestamp": pd.Timestamp("2026-08-09T10:29:00Z"),
                "open": 102.0,
                "high": 104.0,
                "low": 101.0,
                "close": 103.0,
                "volume": 140.0,
            },
            {
                "timestamp": pd.Timestamp("2026-08-09T10:30:00Z"),
                "open": 103.0,
                "high": 105.0,
                "low": 102.0,
                "close": 104.0,
                "volume": 160.0,
            },
        ]
    )

    bars = bars_from_chart_frame(
        frame,
        market="Gold",
        instrument=instrument,
        now="2026-08-09T10:30:35+00:00",
    )

    assert [item.bar_time for item in bars] == [
        "2026-08-09T10:28:00+00:00",
        "2026-08-09T10:29:00+00:00",
    ]
    assert (bars[0].open, bars[0].high, bars[0].low, bars[0].close) == (
        100.0,
        103.0,
        99.0,
        102.0,
    )
    assert bars[0].volume == 120.0
    assert bars[0].sample_count == 0
    assert bars[0].provider == "Saxo OpenAPI"
    assert bars[0].symbol == "GCQ6"


def test_chart_backfill_volume_survives_canonical_store_roundtrip(tmp_path):
    instrument = SaxoInstrument(
        asset="Gold",
        uic=123,
        asset_type="ContractFutures",
        symbol="GCQ6",
    )
    frame = pd.DataFrame(
        [
            {
                "timestamp": pd.Timestamp("2026-08-09T10:29:00Z"),
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 321.0,
            }
        ]
    )
    bars = bars_from_chart_frame(
        frame,
        market="Gold",
        instrument=instrument,
        now="2026-08-09T10:31:00+00:00",
    )
    store = RealtimeMarketDataStore(tmp_path / "ohlcv.db")
    store.save_bar(bars[0])

    loaded = store.load_range(
        market="Gold",
        start="2026-08-09T10:28:00+00:00",
        end="2026-08-09T10:30:00+00:00",
    )

    assert len(loaded) == 1
    assert loaded[0].volume == 321.0


def test_chart_backfill_falls_back_to_close_when_ohlc_fields_are_missing():
    instrument = SaxoInstrument(
        asset="Silver",
        uic=456,
        asset_type="ContractFutures",
        symbol="SIU6",
    )
    frame = pd.DataFrame(
        [{"timestamp": pd.Timestamp("2026-08-09T10:29:00Z"), "close": 62.5}]
    )

    bars = bars_from_chart_frame(
        frame,
        market="Silver",
        instrument=instrument,
        now="2026-08-09T10:31:00+00:00",
    )

    assert len(bars) == 1
    assert (bars[0].open, bars[0].high, bars[0].low, bars[0].close) == (
        62.5,
        62.5,
        62.5,
        62.5,
    )
    assert bars[0].volume is None


def test_backfill_uses_isolated_short_timeout_client():
    client = SaxoClient(
        access_token="test-token",
        base_url=SIM_BASE_URL,
        timeout=20.0,
    )

    backfill = _backfill_client(client)

    assert backfill is not client
    assert backfill.session is not client.session
    assert backfill.base_url == client.base_url
    assert backfill.timeout == BACKFILL_TIMEOUT_SECONDS
