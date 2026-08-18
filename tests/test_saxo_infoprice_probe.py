from __future__ import annotations

from saxo_infoprice_probe import fetch_infoprice_diagnostics
from saxo_provider import SaxoInstrument


class FakeClient:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def _get(self, path, *, params=None):
        self.calls.append((path, params))
        return self.payloads.pop(0)


def test_infoprice_probe_groups_by_asset_type_and_reads_feed_quality():
    client = FakeClient(
        [
            {
                "Data": [
                    {
                        "Uic": 10,
                        "LastUpdated": "2026-08-18T21:55:00Z",
                        "InstrumentPriceDetails": {"IsMarketOpen": True},
                        "Quote": {
                            "Bid": 100.0,
                            "Ask": 100.2,
                            "Mid": 100.1,
                            "DelayedByMinutes": 15,
                            "ErrorCode": "None",
                            "PriceTypeBid": "Indicative",
                            "PriceTypeAsk": "Indicative",
                        },
                        "PriceInfoDetails": {"LastTraded": 100.15},
                    },
                    {
                        "Uic": 11,
                        "InstrumentPriceDetails": {"IsMarketOpen": False},
                        "Quote": {"ErrorCode": "NoAccess"},
                    },
                ]
            },
            {
                "Data": [
                    {
                        "Uic": 20,
                        "Quote": {"Bid": 5000, "Ask": 5001, "DelayedByMinutes": 0},
                    }
                ]
            },
        ]
    )
    instruments = {
        "Brent": SaxoInstrument("Brent", 10, "ContractFutures"),
        "Gold": SaxoInstrument("Gold", 11, "ContractFutures"),
        "sp500 CFD": SaxoInstrument("sp500 CFD", 20, "CfdOnIndex"),
    }

    results = fetch_infoprice_diagnostics(client=client, instruments=instruments)

    assert len(client.calls) == 2
    assert client.calls[0][0] == "trade/v1/infoprices/list"
    assert client.calls[0][1]["AssetType"] == "ContractFutures"
    assert client.calls[0][1]["Uics"] == "10,11"
    assert "Quote" in client.calls[0][1]["FieldGroups"]

    by_market = {item.market: item for item in results}
    assert by_market["Brent"].delayed_by_minutes == 15.0
    assert by_market["Brent"].price_type_bid == "Indicative"
    assert by_market["Brent"].is_market_open is True
    assert by_market["Gold"].error_code == "NoAccess"
    assert by_market["sp500 CFD"].delayed_by_minutes == 0.0


def test_infoprice_probe_marks_missing_instrument_row_explicitly():
    client = FakeClient([{"Data": []}])
    instruments = {"Silver": SaxoInstrument("Silver", 42, "ContractFutures")}

    result = fetch_infoprice_diagnostics(client=client, instruments=instruments)[0]

    assert result.market == "Silver"
    assert result.error_code == "MISSING_FROM_RESPONSE"
    assert result.bid is None
    assert result.delayed_by_minutes is None
