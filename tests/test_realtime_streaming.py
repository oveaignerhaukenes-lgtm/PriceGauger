from __future__ import annotations

from datetime import datetime, timezone
import json
import struct
from types import SimpleNamespace

from realtime_market_data import MinuteBarAggregator, RealtimeMarketDataStore, RealtimeQuote, StreamStatus
from saxo_provider import LIVE_BASE_URL, SIM_BASE_URL, SaxoInstrument
from saxo_streaming import _stream_url, merge_delta, parse_stream_frame, quote_from_snapshot


def _wire_message(message_id: int, reference_id: str, payload: dict) -> bytes:
    ref = reference_id.encode("ascii")
    raw = json.dumps(payload).encode("utf-8")
    return (
        struct.pack("<Q", message_id)
        + b"\x00\x00"
        + bytes([len(ref)])
        + ref
        + b"\x00"
        + struct.pack("<I", len(raw))
        + raw
    )


def test_stream_url_uses_current_saxo_environment_endpoints():
    sim = SimpleNamespace(base_url=SIM_BASE_URL)
    live = SimpleNamespace(base_url=LIVE_BASE_URL)

    assert _stream_url(sim, "pg-test") == (
        "wss://sim-streaming.saxobank.com/sim/oapi/streaming/ws/connect?contextId=pg-test"
    )
    assert _stream_url(live, "pg-test") == (
        "wss://live-streaming.saxobank.com/oapi/streaming/ws/connect?contextId=pg-test"
    )
    assert "streaming.saxobank.com/sim/openapi/streamingws" not in _stream_url(sim, "pg-test")


def test_parse_stream_frame_supports_multiple_saxo_messages():
    frame = _wire_message(10, "PG01", {"Quote": {"Bid": 100.0}}) + _wire_message(
        11, "_heartbeat", {"Heartbeats": []}
    )

    messages = parse_stream_frame(frame)

    assert [item.message_id for item in messages] == [10, 11]
    assert messages[0].reference_id == "PG01"
    assert messages[0].payload["Quote"]["Bid"] == 100.0
    assert messages[1].reference_id == "_heartbeat"


def test_merge_delta_preserves_unchanged_quote_fields():
    current = {"Quote": {"Bid": 100.0, "Ask": 101.0}, "PriceInfoDetails": {"DelayedByMinutes": 0}}
    update = {"Quote": {"Bid": 100.5}}

    merged = merge_delta(current, update)

    assert merged["Quote"] == {"Bid": 100.5, "Ask": 101.0}
    assert merged["PriceInfoDetails"]["DelayedByMinutes"] == 0


def test_quote_from_snapshot_applies_instrument_multiplier():
    instrument = SaxoInstrument(
        asset="Silver",
        uic=45184335,
        asset_type="ContractFutures",
        symbol="SIU6",
        price_multiplier=0.01,
    )

    quote = quote_from_snapshot(
        market="Silver",
        instrument=instrument,
        payload={"Quote": {"Bid": 6200.0, "Ask": 6220.0}},
        observed_at="2026-08-09T10:00:01+00:00",
    )

    assert quote is not None
    assert quote.bid == 62.0
    assert quote.ask == 62.2
    assert round(quote.price or 0.0, 3) == 62.1


def test_minute_aggregator_emits_only_when_next_minute_arrives():
    agg = MinuteBarAggregator()
    base = {
        "market": "Gold",
        "bid": None,
        "ask": None,
        "provider": "Saxo OpenAPI",
        "uic": 1,
        "asset_type": "ContractFutures",
        "symbol": "GC",
    }

    assert agg.add(RealtimeQuote(observed_at="2026-08-09T10:00:01+00:00", last=100.0, **base)) is None
    assert agg.add(RealtimeQuote(observed_at="2026-08-09T10:00:25+00:00", last=103.0, **base)) is None
    assert agg.add(RealtimeQuote(observed_at="2026-08-09T10:00:55+00:00", last=99.0, **base)) is None
    completed = agg.add(RealtimeQuote(observed_at="2026-08-09T10:01:02+00:00", last=101.0, **base))

    assert completed is not None
    assert completed.bar_time == "2026-08-09T10:00:00+00:00"
    assert (completed.open, completed.high, completed.low, completed.close) == (100.0, 103.0, 99.0, 99.0)
    assert completed.sample_count == 3


def test_realtime_store_persists_one_minute_bars_and_status(tmp_path):
    path = tmp_path / "realtime.db"
    store = RealtimeMarketDataStore(path)
    agg = MinuteBarAggregator()
    template = dict(
        market="Brent",
        bid=None,
        ask=None,
        provider="Saxo OpenAPI",
        uic=43660942,
        asset_type="ContractFutures",
        symbol="LCOV6",
    )
    agg.add(RealtimeQuote(observed_at="2026-08-09T10:00:01+00:00", last=80.0, **template))
    bar = agg.add(RealtimeQuote(observed_at="2026-08-09T10:01:01+00:00", last=81.0, **template))
    assert bar is not None
    store.save_bar(bar)
    store.save_status(
        StreamStatus(
            market="Brent",
            updated_at=datetime(2026, 8, 9, 10, 1, tzinfo=timezone.utc).isoformat(),
            state="STREAMING",
            requested_refresh_ms=1000,
            actual_refresh_ms=1000,
            delay_minutes=0,
            last_quote_at="2026-08-09T10:01:01+00:00",
        )
    )

    bars = store.load_range(
        market="Brent",
        start="2026-08-09T09:59:00+00:00",
        end="2026-08-09T10:02:00+00:00",
    )
    statuses = store.load_statuses()

    assert len(bars) == 1
    assert bars[0].close == 80.0
    assert bars[0].uic == 43660942
    assert statuses[0].market == "Brent"
    assert statuses[0].actual_refresh_ms == 1000
