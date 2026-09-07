from __future__ import annotations

from datetime import datetime, timezone

import futures_rollover_discovery_v2 as discovery
import futures_rollover_v1 as rollover
from instrument_registry_v2 import InstrumentSourceV2
from saxo_provider import SaxoInstrument


class _Client:
    def __init__(self, *, include_exact=True, primary=60000002):
        self.include_exact = include_exact
        self.primary = primary
        self.search_calls = []

    def instrument_details(self, instrument: SaxoInstrument):
        if int(instrument.uic) == 50419383:
            return {
                "Uic": 50419383,
                "ExpiryDateTime": "2026-08-27T18:30:00Z",
                "IsTradable": False,
                "Symbol": "NGU6",
                "Description": "Natural Gas Sep 2026",
            }
        return {
            "Uic": int(instrument.uic),
            "PrimaryListing": int(instrument.uic),
            "ExpiryDateTime": "2026-10-28T18:30:00Z",
            "IsTradable": True,
            "Symbol": "NGV6",
            "Description": "Natural Gas Oct 2026",
        }

    def _get(self, path, params=None):
        assert path == "ref/v1/instruments"
        self.search_calls.append(dict(params or {}))
        rows = [
            {
                "Identifier": 60000002,
                "PrimaryListing": 60000002,
                "AssetType": "ContractFutures",
                "Symbol": "NGV6",
                "Description": "Natural Gas Oct 2026",
            }
        ]
        if self.include_exact:
            rows.insert(
                0,
                {
                    "Identifier": 50419383,
                    "PrimaryListing": self.primary,
                    "AssetType": "ContractFutures",
                    "Symbol": "NGU6",
                    "Description": "Natural Gas Sep 2026",
                },
            )
        return {"Data": rows}


def _source():
    return InstrumentSourceV2(
        market_id=9,
        market_name="Natural Gas",
        instrument_id=91,
        instrument_type="future",
        display_name="Natural Gas Sep 2026",
        provider="saxo",
        provider_instrument_id="50419383",
        asset_type="ContractFutures",
        symbol="NGU6",
        price_multiplier=1.0,
        metadata={"expiry": "2026-08-27T18:30:00Z"},
    )


def test_search_fallback_recovers_primary_listing_only_from_exact_old_uic(monkeypatch) -> None:
    client = _Client()
    monkeypatch.setattr(rollover, "list_subscribed_sources_v2", lambda provider=None: (_source(),))
    applied = []
    monkeypatch.setattr(rollover, "_apply_rollover", lambda **kwargs: applied.append(kwargs) or 92)

    summary = discovery.resolve_saxo_futures_rollovers_with_discovery_v2(
        client=client,
        now=datetime(2026, 9, 7, 0, 30, tzinfo=timezone.utc),
    )

    assert summary.rolled == 1
    assert summary.failed == 0
    assert applied[0]["candidate"].uic == 60000002
    assert client.search_calls[0]["Keywords"] == "Natural Gas"
    assert client.search_calls[0]["AssetTypes"] == "ContractFutures"


def test_search_fallback_fails_closed_when_old_uic_is_not_in_results(monkeypatch) -> None:
    client = _Client(include_exact=False)
    monkeypatch.setattr(rollover, "list_subscribed_sources_v2", lambda provider=None: (_source(),))
    applied = []
    monkeypatch.setattr(rollover, "_apply_rollover", lambda **kwargs: applied.append(kwargs) or 92)

    summary = discovery.resolve_saxo_futures_rollovers_with_discovery_v2(
        client=client,
        now=datetime(2026, 9, 7, 0, 30, tzinfo=timezone.utc),
    )

    assert summary.eligible == 1
    assert summary.rolled == 0
    assert summary.failed == 1
    assert applied == []


def test_same_uic_primary_listing_is_not_accepted_as_rollover_candidate(monkeypatch) -> None:
    client = _Client(primary=50419383)
    monkeypatch.setattr(rollover, "list_subscribed_sources_v2", lambda provider=None: (_source(),))
    applied = []
    monkeypatch.setattr(rollover, "_apply_rollover", lambda **kwargs: applied.append(kwargs) or 92)

    summary = discovery.resolve_saxo_futures_rollovers_with_discovery_v2(
        client=client,
        now=datetime(2026, 9, 7, 0, 30, tzinfo=timezone.utc),
    )

    assert summary.rolled == 0
    assert summary.failed == 1
    assert applied == []
