from __future__ import annotations

from saxo_discover import discover_pricegauger_instruments
from saxo_provider import SaxoInstrument


class FakeClient:
    def __init__(self) -> None:
        self.calls = []

    def search_instruments(self, keywords: str, *, asset_types: str):
        self.calls.append((keywords, asset_types))
        return [SaxoInstrument(keywords, 99, "ContractFutures", symbol="NG")]


def test_pricegauger_discovery_adds_natural_gas_without_guessing_configuration(monkeypatch):
    monkeypatch.setattr(
        "saxo_discover.discover_instruments",
        lambda client: {"Gold": [SaxoInstrument("Gold", 7, "ContractFutures")]},
    )
    client = FakeClient()

    discovered = discover_pricegauger_instruments(client)

    assert set(discovered) == {"Gold", "Natural Gas"}
    assert discovered["Natural Gas"][0].uic == 99
    assert client.calls == [("Natural Gas", "ContractFutures,CfdOnFutures")]
