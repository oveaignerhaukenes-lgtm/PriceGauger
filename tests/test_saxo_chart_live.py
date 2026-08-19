from __future__ import annotations

from datetime import datetime, timezone

import pytest

from saxo_chart_live import (
    FormingCandle1m,
    FormingCandleStore,
    create_chart_subscription,
    forming_candle_from_chart_payload,
    merge_forming_candle_for_display,
)
from saxo_provider import SaxoClient, SaxoInstrument
from trading_desk import ChartBar


class FakeResponse:
    def __init__(self, payload, status_code=201):
        self._payload = payload
        self.status_code = status_code
        self.ok = status_code < 400

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.headers = {}
        self.calls = []

    def post(self, url, json=None, timeout=None):
        self.calls.append((url, json, timeout))
        return FakeResponse(self.payload)


def _instrument() -> SaxoInstrument:
    return SaxoInstrument(
        "Silver",
        45184335,
        "ContractFutures",
        symbol="SILVER",
        price_multiplier=0.01,
    )


def test_chart_subscription_requests_one_minute_stream_at_requested_refresh():
    session = FakeSession({"Snapshot": {"Data": []}, "RefreshRate": 1000})
    client = SaxoClient("token", session=session)

    create_chart_subscription(
        client,
        context_id="ctx",
        reference_id="PGC01",
        instrument=_instrument(),
        refresh_ms=1000,
    )

    url, body, _ = session.calls[0]
    assert url.endswith("/chart/v3/charts/subscriptions")
    assert body["Arguments"]["Uic"] == 45184335
    assert body["Arguments"]["AssetType"] == "ContractFutures"
    assert body["Arguments"]["Horizon"] == 1
    assert body["Arguments"]["Count"] == 2
    assert body["RefreshRate"] == 1000
    assert body["ContextId"] == "ctx"
    assert body["ReferenceId"] == "PGC01"


def test_forming_candle_uses_latest_chart_row_and_price_multiplier():
    candle = forming_candle_from_chart_payload(
        market="Silver",
        instrument=_instrument(),
        payload={
            "ChartInfo": {"DelayedByMinutes": 15},
            "Data": [
                {
                    "Time": "2026-08-18T22:20:00Z",
                    "OpenBid": 6000,
                    "HighBid": 6010,
                    "LowBid": 5990,
                    "CloseBid": 6005,
                },
                {
                    "Time": "2026-08-18T22:21:00Z",
                    "OpenBid": 6005,
                    "HighBid": 6020,
                    "LowBid": 6000,
                    "CloseBid": 6015,
                    "Volume": 12,
                },
            ],
        },
        source_event_at="2026-08-18T22:36:01Z",
    )

    assert candle is not None
    assert candle.bar_time == "2026-08-18T22:21:00+00:00"
    assert candle.open == pytest.approx(60.05)
    assert candle.high == pytest.approx(60.20)
    assert candle.low == pytest.approx(60.00)
    assert candle.close == pytest.approx(60.15)
    assert candle.volume == 12
    assert candle.delayed_by_minutes == 15


def test_forming_candle_store_is_separate_from_canonical_store(tmp_path):
    store = FormingCandleStore(tmp_path / "chart.db")
    candle = FormingCandle1m(
        market="Gold",
        bar_time="2026-08-18T22:21:00+00:00",
        open=4400,
        high=4402,
        low=4399,
        close=4401,
        volume=None,
        provider="Saxo chart stream",
        uic=7,
        asset_type="ContractFutures",
        symbol="GOLD",
        delayed_by_minutes=15,
        source_event_at="2026-08-18T22:36:01+00:00",
        updated_at="2026-08-18T22:36:01+00:00",
    )

    store.save(candle)

    assert store.load(market="Gold") == candle
    assert store.load(market="Silver") is None


def test_forming_candle_overlays_only_last_display_bucket():
    completed = (
        ChartBar("Gold", "2026-08-18T22:15:00+00:00", 100, 104, 99, 102, None),
        ChartBar("Gold", "2026-08-18T22:20:00+00:00", 102, 105, 101, 104, None),
    )
    forming = FormingCandle1m(
        market="Gold",
        bar_time="2026-08-18T22:23:00+00:00",
        open=104,
        high=108,
        low=103,
        close=107,
        volume=7,
        provider="Saxo chart stream",
        uic=7,
        asset_type="ContractFutures",
        symbol="GOLD",
        delayed_by_minutes=15,
        source_event_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
    )

    merged = merge_forming_candle_for_display(completed, forming=forming, timeframe="5m")

    assert len(merged) == 2
    assert merged[-1].bar_time == "2026-08-18T22:20:00+00:00"
    assert merged[-1].open == 102
    assert merged[-1].high == 108
    assert merged[-1].low == 101
    assert merged[-1].close == 107
    assert merged[-1].volume is None


def test_stale_forming_candle_cannot_rewrite_older_display_history():
    completed = (
        ChartBar("Gold", "2026-08-18T22:20:00+00:00", 102, 105, 101, 104, None),
    )
    forming = FormingCandle1m(
        market="Gold",
        bar_time="2026-08-18T22:19:00+00:00",
        open=100,
        high=200,
        low=50,
        close=150,
        volume=None,
        provider="Saxo chart stream",
        uic=7,
        asset_type="ContractFutures",
        symbol="GOLD",
        delayed_by_minutes=15,
        source_event_at="2026-08-18T22:34:00+00:00",
        updated_at="2026-08-18T22:34:00+00:00",
    )

    assert merge_forming_candle_for_display(completed, forming=forming, timeframe="1m") == completed
