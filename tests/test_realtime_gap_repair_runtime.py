from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import realtime_gap_repair as gap_repair
from realtime_gap_repair import GapRepairingSaxoRealtimeService
from realtime_market_data import RealtimeQuote
from saxo_provider import SaxoInstrument
from saxo_streaming import SaxoStreamMessage


def _instrument(asset: str, uic: int) -> SaxoInstrument:
    return SaxoInstrument(
        asset=asset,
        uic=uic,
        asset_type="ContractFutures",
        symbol=asset.upper(),
    )


def _service(tmp_path, *, instruments=None) -> GapRepairingSaxoRealtimeService:
    configured = instruments or {"Gold": _instrument("Gold", 101)}
    client = SimpleNamespace(timeout=5.0, base_url="https://example.invalid", session=SimpleNamespace())
    return GapRepairingSaxoRealtimeService(
        db_path=str(tmp_path / "realtime.db"),
        client=client,
        instruments=configured,
    )


def test_first_snapshot_quote_is_persisted_despite_status_throttle(tmp_path):
    service = _service(tmp_path)
    service._status(
        "Gold",
        "SUBSCRIBED",
        reference_id="PG01",
        detail="subscription active",
    )

    service._consume_quote(
        RealtimeQuote(
            market="Gold",
            observed_at="2026-08-18T15:00:01+00:00",
            bid=4400.0,
            ask=4401.0,
            last=None,
            uic=101,
            asset_type="ContractFutures",
            symbol="GOLD",
        )
    )

    status = {item.market: item for item in service.store.load_statuses()}["Gold"]
    assert status.state == "STREAMING"
    assert status.last_quote_at == "2026-08-18T15:00:01+00:00"


def test_market_quote_staleness_uses_in_memory_observation(tmp_path):
    service = _service(tmp_path)
    now = datetime(2026, 8, 18, 15, 10, tzinfo=timezone.utc)
    service._status(
        "Gold",
        "STREAMING",
        last_quote_at=(now - timedelta(seconds=30)).isoformat(),
    )
    assert service._market_quote_is_stale("Gold", now=now) is False

    service._status(
        "Gold",
        "STREAMING",
        last_quote_at=(now - timedelta(minutes=3)).isoformat(),
    )
    assert service._market_quote_is_stale("Gold", now=now) is True


def test_heartbeat_message_drives_stale_repair_cadence(tmp_path):
    service = _service(tmp_path)
    calls: list[bool] = []
    service._start_stale_repair_if_due = lambda: calls.append(True) or True  # type: ignore[method-assign]

    service.handle_message(
        SaxoStreamMessage(
            message_id=1,
            reference_id="_heartbeat",
            payload_format=0,
            payload={"Heartbeats": []},
        )
    )

    assert calls == [True]


def test_stale_repair_only_fetches_markets_without_fresh_quotes(tmp_path, monkeypatch):
    instruments = {
        "Gold": _instrument("Gold", 101),
        "Silver": _instrument("Silver", 202),
    }
    service = _service(tmp_path, instruments=instruments)
    now = datetime.now(timezone.utc)
    service._status(
        "Gold",
        "STREAMING",
        last_quote_at=(now - timedelta(seconds=10)).isoformat(),
    )
    service._status("Silver", "SUBSCRIBED")

    repaired: list[str] = []

    monkeypatch.setattr(gap_repair, "_backfill_client", lambda client: object())

    def fake_repair(**kwargs):
        repaired.append(kwargs["market"])
        return 3

    monkeypatch.setattr(gap_repair, "repair_recent_market_history", fake_repair)

    service._run_stale_repair()

    assert repaired == ["Silver"]
