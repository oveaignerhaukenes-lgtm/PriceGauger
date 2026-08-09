from __future__ import annotations

from realtime_market_data import RealtimeBar1m, RealtimeMarketDataStore, StreamStatus


def _bar(*, market: str, stamp: str, close: float, symbol: str) -> RealtimeBar1m:
    return RealtimeBar1m(
        market=market,
        bar_time=stamp,
        open=close,
        high=close,
        low=close,
        close=close,
        sample_count=1,
        provider="Saxo OpenAPI",
        uic=123,
        asset_type="ContractFutures",
        symbol=symbol,
    )


def test_load_latest_bar_returns_newest_contract_bar(tmp_path):
    path = tmp_path / "realtime.db"
    store = RealtimeMarketDataStore(path)
    store.save_bar(_bar(market="Gold", stamp="2026-08-09T10:00:00+00:00", close=100.0, symbol="GCQ6"))
    store.save_bar(_bar(market="Gold", stamp="2026-08-09T10:02:00+00:00", close=102.0, symbol="GCQ6"))
    store.save_bar(_bar(market="Silver", stamp="2026-08-09T10:03:00+00:00", close=60.0, symbol="SIU6"))

    latest = store.load_latest_bar(market="Gold")

    assert latest is not None
    assert latest.bar_time == "2026-08-09T10:02:00+00:00"
    assert latest.close == 102.0
    assert latest.symbol == "GCQ6"
    assert store.load_latest_bar(market="Brent") is None


def test_stream_status_preserves_refresh_and_delay_metadata(tmp_path):
    path = tmp_path / "realtime.db"
    store = RealtimeMarketDataStore(path)
    store.save_status(
        StreamStatus(
            market="Gold",
            updated_at="2026-08-09T10:03:01+00:00",
            state="STREAMING",
            requested_refresh_ms=1000,
            actual_refresh_ms=1000,
            delay_minutes=0.0,
            last_quote_at="2026-08-09T10:03:00+00:00",
        )
    )
    store.save_status(
        StreamStatus(
            market="DXY",
            updated_at="2026-08-09T10:03:01+00:00",
            state="SUBSCRIBED",
            requested_refresh_ms=1000,
            actual_refresh_ms=5000,
            delay_minutes=15.0,
        )
    )

    statuses = {item.market: item for item in store.load_statuses()}

    assert statuses["Gold"].actual_refresh_ms == 1000
    assert statuses["Gold"].delay_minutes == 0.0
    assert statuses["DXY"].actual_refresh_ms == 5000
    assert statuses["DXY"].delay_minutes == 15.0
