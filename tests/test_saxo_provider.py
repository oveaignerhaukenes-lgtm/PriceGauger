from __future__ import annotations

from datetime import datetime, timezone

from market_data import MarketRequest
from saxo_provider import SaxoClient, SaxoInstrument, SaxoPriceProvider, instrument_is_unexpired


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.ok = status_code < 400
        self.text = "error" if not self.ok else ""

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.headers = {}
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params, timeout))
        return FakeResponse(self.payload)


def test_chart_normalizes_bid_ohlc():
    session = FakeSession(
        {
            "Data": [
                {
                    "Time": "2026-07-23T21:55:00Z",
                    "OpenBid": 100.66,
                    "HighBid": 101.15,
                    "LowBid": 100.62,
                    "CloseBid": 101.04,
                }
            ]
        }
    )
    client = SaxoClient("token", session=session)
    instrument = SaxoInstrument("DXY", 43074091, "ContractFutures")

    frame = client.chart(instrument, horizon_minutes=5, count=20)

    assert list(frame.columns) == ["timestamp", "open", "high", "low", "close"]
    assert frame.iloc[0]["close"] == 101.04
    assert session.calls[0][1]["Uic"] == 43074091
    assert session.calls[0][1]["Horizon"] == 5


def test_chart_applies_price_multiplier_to_ohlc_not_volume():
    session = FakeSession(
        {
            "Data": [
                {
                    "Time": "2026-07-24T00:20:00Z",
                    "OpenBid": 5776.0,
                    "HighBid": 5779.5,
                    "LowBid": 5776.0,
                    "CloseBid": 5779.5,
                    "Volume": 4,
                }
            ]
        }
    )
    client = SaxoClient("token", session=session)
    instrument = SaxoInstrument("Silver", 45184335, "ContractFutures", price_multiplier=0.01)

    frame = client.chart(instrument, horizon_minutes=5, count=20)

    assert frame.iloc[0]["open"] == 57.76
    assert frame.iloc[0]["close"] == 57.795
    assert frame.iloc[0]["volume"] == 4


def test_instrument_details_uses_expected_endpoint():
    session = FakeSession({"Uic": 45184335, "Format": {"Decimals": 1}})
    client = SaxoClient("token", session=session)
    instrument = SaxoInstrument("Silver", 45184335, "ContractFutures")

    payload = client.instrument_details(instrument)

    assert payload["Uic"] == 45184335
    assert session.calls[0][0].endswith("/ref/v1/instruments/details/45184335/ContractFutures")
    assert session.calls[0][1] == {"FieldGroups": "MarketData"}


def test_provider_requires_configured_asset():
    client = SaxoClient("token", session=FakeSession({"Data": []}))
    provider = SaxoPriceProvider(
        client,
        {"Brent": SaxoInstrument("Brent", 123, "ContractFutures")},
    )

    assert provider.supports(MarketRequest("Brent", "5min", 20, {}))
    assert not provider.supports(MarketRequest("Gold", "5min", 20, {}))


def test_expiry_filter():
    now = datetime(2026, 7, 23, tzinfo=timezone.utc)
    assert instrument_is_unexpired(SaxoInstrument("Brent", 1, "ContractFutures", expiry="2026-08-01"), now)
    assert not instrument_is_unexpired(SaxoInstrument("Brent", 1, "ContractFutures", expiry="2026-07-01"), now)
