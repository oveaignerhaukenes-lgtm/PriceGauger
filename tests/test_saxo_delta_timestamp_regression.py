from __future__ import annotations

from saxo_provider import SaxoInstrument
from saxo_streaming import SaxoRealtimeService, SaxoStreamMessage


def test_stream_delta_without_timestamp_uses_receipt_time_not_stale_snapshot(tmp_path):
    instrument = SaxoInstrument(
        asset="Gold",
        uic=123,
        asset_type="ContractFutures",
        symbol="GC",
        price_multiplier=1.0,
    )
    service = SaxoRealtimeService(
        db_path=str(tmp_path / "stream.db"),
        client=object(),
        instruments={"Gold": instrument},
    )
    ref = "PG01TEST"
    service.reference_to_market[ref] = "Gold"
    service.snapshots[ref] = {
        "Quote": {"Bid": 100.0, "Ask": 101.0},
        "Timestamp": "2026-08-18T10:00:05+00:00",
    }

    observed = []
    service._consume_quote = observed.append  # type: ignore[method-assign]

    service.handle_message(
        SaxoStreamMessage(
            message_id=1,
            reference_id=ref,
            payload_format=0,
            payload={"Quote": {"Bid": 102.0}},
        ),
        received_at="2026-08-18T10:01:07+00:00",
    )

    assert len(observed) == 1
    quote = observed[0]
    assert quote.observed_at == "2026-08-18T10:01:07+00:00"
    assert quote.bid == 102.0
    assert quote.ask == 101.0


def test_stream_delta_timestamp_overrides_receipt_time(tmp_path):
    instrument = SaxoInstrument(
        asset="Gold",
        uic=123,
        asset_type="ContractFutures",
        symbol="GC",
        price_multiplier=1.0,
    )
    service = SaxoRealtimeService(
        db_path=str(tmp_path / "stream.db"),
        client=object(),
        instruments={"Gold": instrument},
    )
    ref = "PG01TEST"
    service.reference_to_market[ref] = "Gold"
    service.snapshots[ref] = {"Quote": {"Bid": 100.0, "Ask": 101.0}}

    observed = []
    service._consume_quote = observed.append  # type: ignore[method-assign]

    service.handle_message(
        SaxoStreamMessage(
            message_id=2,
            reference_id=ref,
            payload_format=0,
            payload={
                "Quote": {"Ask": 103.0},
                "Timestamp": "2026-08-18T10:02:03+00:00",
            },
        ),
        received_at="2026-08-18T10:02:09+00:00",
    )

    assert len(observed) == 1
    quote = observed[0]
    assert quote.observed_at == "2026-08-18T10:02:03+00:00"
    assert quote.bid == 100.0
    assert quote.ask == 103.0
