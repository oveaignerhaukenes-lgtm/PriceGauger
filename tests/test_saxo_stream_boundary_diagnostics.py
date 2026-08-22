from __future__ import annotations

import logging

from saxo_provider import SaxoInstrument
from saxo_streaming import SaxoRealtimeService, SaxoStreamMessage, _should_log_count


def _service(tmp_path):
    instrument = SaxoInstrument(
        asset="Gold",
        uic=123,
        asset_type="ContractFutures",
        symbol="GC",
        price_multiplier=1.0,
    )
    return SaxoRealtimeService(
        db_path=str(tmp_path / "stream.db"),
        client=object(),
        instruments={"Gold": instrument},
    )


def test_boundary_diagnostic_log_sampling_is_bounded():
    assert _should_log_count(1)
    assert _should_log_count(2)
    assert _should_log_count(3)
    assert not _should_log_count(4)
    assert not _should_log_count(99)
    assert _should_log_count(100)


def test_unknown_reference_is_counted_and_logged(tmp_path, caplog):
    service = _service(tmp_path)
    message = SaxoStreamMessage(
        message_id=7,
        reference_id="OTHERREF",
        payload_format=0,
        payload={"Quote": {"Bid": 100.0}},
    )

    with caplog.at_level(logging.WARNING, logger="pricegauger.saxo_stream"):
        service.handle_message(message)

    assert service._unknown_reference_counts["OTHERREF"] == 1
    assert "unknown-reference diagnostic" in caplog.text
    assert "OTHERREF" in caplog.text


def test_known_message_counts_quote_production(tmp_path, caplog):
    service = _service(tmp_path)
    ref = "PG01TEST"
    service.reference_to_market[ref] = "Gold"
    service.snapshots[ref] = {"Quote": {"Bid": 100.0, "Ask": 101.0}}
    observed = []
    service._consume_quote = observed.append  # type: ignore[method-assign]

    message = SaxoStreamMessage(
        message_id=8,
        reference_id=ref,
        payload_format=0,
        payload={"Quote": {"Bid": 102.0}},
    )

    with caplog.at_level(logging.INFO, logger="pricegauger.saxo_stream"):
        service.handle_message(message, received_at="2026-08-22T08:00:00+00:00")

    assert service._message_counts[ref] == 1
    assert service._quote_message_counts[ref] == 1
    assert len(observed) == 1
    assert "quote_producing=True" in caplog.text


def test_control_message_is_observed_without_changing_behavior(tmp_path, caplog):
    service = _service(tmp_path)
    message = SaxoStreamMessage(
        message_id=9,
        reference_id="_HEARTBEAT",
        payload_format=0,
        payload={"Heartbeats": []},
    )

    with caplog.at_level(logging.INFO, logger="pricegauger.saxo_stream"):
        service.handle_message(message)

    assert service._control_message_counts["_HEARTBEAT"] == 1
    assert "control diagnostic" in caplog.text
