from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import realtime_gap_repair as gap_repair
from realtime_gap_repair import (
    GapRepairingSaxoRealtimeService,
    _closed_snapshot_cutoff,
    repair_closed_market_realtime_tail,
)
from realtime_market_data import RealtimeBar1m
from saxo_provider import SaxoInstrument
from saxo_streaming import SaxoStreamMessage


def _instrument() -> SaxoInstrument:
    return SaxoInstrument(
        asset="US Tech 100",
        uic=4912,
        asset_type="CfdOnIndex",
        symbol="NAS",
        price_multiplier=1.0,
    )


def _service(tmp_path) -> GapRepairingSaxoRealtimeService:
    client = SimpleNamespace(timeout=5.0, base_url="https://example.invalid", session=SimpleNamespace())
    return GapRepairingSaxoRealtimeService(
        db_path=str(tmp_path / "realtime.db"),
        client=client,
        instruments={"US Tech 100": _instrument()},
    )


def test_lastupdated_only_delta_does_not_replay_merged_quote(tmp_path):
    service = _service(tmp_path)
    ref = "PG01TEST"
    service.reference_to_market[ref] = "US Tech 100"
    service.snapshots[ref] = {
        "LastUpdated": "2026-09-04T20:59:59+00:00",
        "Quote": {"Bid": 29491.4, "Ask": 29493.4},
    }
    observed = []
    service._consume_quote = observed.append  # type: ignore[method-assign]
    service._start_stale_repair_if_due = lambda: False  # type: ignore[method-assign]

    service.handle_message(
        SaxoStreamMessage(
            message_id=1,
            reference_id=ref,
            payload_format=0,
            payload={"LastUpdated": "2026-09-05T03:33:33+00:00"},
        ),
        received_at="2026-09-05T03:33:34+00:00",
    )

    assert observed == []
    assert service.snapshots[ref]["LastUpdated"] == "2026-09-05T03:33:33+00:00"
    assert service._quote_message_counts.get(ref, 0) == 0


def test_actual_open_price_delta_still_produces_quote(tmp_path):
    service = _service(tmp_path)
    ref = "PG01TEST"
    service.reference_to_market[ref] = "US Tech 100"
    service.snapshots[ref] = {"Quote": {"Bid": 29491.4, "Ask": 29493.4}}
    observed = []
    service._consume_quote = observed.append  # type: ignore[method-assign]
    service._start_stale_repair_if_due = lambda: False  # type: ignore[method-assign]

    service.handle_message(
        SaxoStreamMessage(
            message_id=2,
            reference_id=ref,
            payload_format=0,
            payload={
                "LastUpdated": "2026-09-07T07:00:01+00:00",
                "Quote": {"Bid": 29510.0, "Ask": 29512.0},
            },
        ),
        received_at="2026-09-07T07:00:01+00:00",
    )

    assert len(observed) == 1
    assert observed[0].price == 29511.0


def test_explicit_old_indicative_price_delta_is_not_canonical_quote(tmp_path):
    service = _service(tmp_path)
    ref = "PG01TEST"
    service.reference_to_market[ref] = "US Tech 100"
    service.snapshots[ref] = {"Quote": {"Bid": 29491.4, "Ask": 29493.4}}
    observed = []
    service._consume_quote = observed.append  # type: ignore[method-assign]
    service._start_stale_repair_if_due = lambda: False  # type: ignore[method-assign]

    service.handle_message(
        SaxoStreamMessage(
            message_id=3,
            reference_id=ref,
            payload_format=0,
            payload={
                "LastUpdated": "2026-09-05T04:00:00+00:00",
                "Quote": {
                    "Bid": 29491.4,
                    "Ask": 29493.4,
                    "PriceTypeBid": "OldIndicative",
                    "PriceTypeAsk": "OldIndicative",
                    "MarketState": "Closed",
                },
            },
        )
    )

    assert observed == []


def test_closed_snapshot_cutoff_uses_provider_lastupdated():
    cutoff = _closed_snapshot_cutoff(
        {
            "LastUpdated": "2026-09-04T20:59:59.003Z",
            "Quote": {
                "Bid": 29491.4,
                "Ask": 29493.4,
                "PriceTypeBid": "OldIndicative",
                "PriceTypeAsk": "OldIndicative",
                "MarketState": "Closed",
            },
        }
    )
    assert cutoff == datetime(2026, 9, 4, 20, 59, tzinfo=timezone.utc)


def test_closed_market_tail_repair_removes_only_rows_after_cutoff(tmp_path, monkeypatch):
    service = _service(tmp_path)
    monkeypatch.setattr(gap_repair, "using_postgres", lambda: False)
    instrument = _instrument()
    for stamp, price in (
        ("2026-09-04T20:59:00+00:00", 29492.0),
        ("2026-09-04T21:00:00+00:00", 29492.4),
        ("2026-09-05T03:31:00+00:00", 29492.4),
    ):
        service.store.save_bar(
            RealtimeBar1m(
                market="US Tech 100",
                bar_time=stamp,
                open=price,
                high=price,
                low=price,
                close=price,
                sample_count=1,
                provider="Saxo OpenAPI",
                uic=4912,
                asset_type="CfdOnIndex",
                symbol="NAS",
            )
        )

    removed = repair_closed_market_realtime_tail(
        store=service.store,
        market="US Tech 100",
        instrument=instrument,
        cutoff=datetime(2026, 9, 4, 20, 59, tzinfo=timezone.utc),
    )

    assert removed == 2
    bars = service.store.load_range(
        market="US Tech 100",
        start="2026-09-04T20:00:00+00:00",
        end="2026-09-05T04:00:00+00:00",
    )
    assert [bar.bar_time for bar in bars] == ["2026-09-04T20:59:00+00:00"]
