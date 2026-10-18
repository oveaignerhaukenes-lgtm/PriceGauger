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
    assert client.search_calls[0]["Uics"] == "50419383"
    assert client.search_calls[0]["IncludeNonTradable"] is True
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



def test_nontradable_expired_uic_is_found_only_with_explicit_include_flag(monkeypatch):
    class MissingFromDefaultSearch(_Client):
        def _get(self, path, params=None):
            self.search_calls.append(dict(params or {}))
            if params.get("Uics") == "50419383" and params.get("IncludeNonTradable") is True:
                return {"Data": [{"Identifier": 50419383, "PrimaryListing": 60000002,
                                  "AssetType": "ContractFutures"}]}
            return {"Data": []}

    client = MissingFromDefaultSearch()
    monkeypatch.setattr(rollover, "list_subscribed_sources_v2", lambda provider=None: (_source(),))
    done = []
    monkeypatch.setattr(rollover, "_apply_rollover", lambda **kw: done.append(kw) or 92)
    result = discovery.resolve_saxo_futures_rollovers_with_discovery_v2(
        client=client, now=datetime(2026, 9, 7, tzinfo=timezone.utc),
    )
    assert result.rolled == 1
    assert len(client.search_calls) == 1
    assert client.search_calls[0]["IncludeNonTradable"] is True
    assert done[0]["candidate"].uic == 60000002


def test_exact_uic_query_can_fallback_to_keyword_but_never_to_similar_instrument(monkeypatch):
    class FallbackClient(_Client):
        def _get(self, path, params=None):
            self.search_calls.append(dict(params or {}))
            if "Uics" in params:
                # Some Saxo accounts might not return archived UIC directly.
                return {"Data": []}
            return {"Data": [
                {"Identifier": 60000003, "PrimaryListing": 60000003,
                 "AssetType": "ContractFutures",
                 "Description": "Natural Gas Nov 2026"},
                {"Identifier": 50419383, "PrimaryListing": 60000002,
                 "AssetType": "ContractFutures",
                 "Description": "Natural Gas Sep 2026"}
            ]}
    client = FallbackClient()
    result = discovery._search_primary_listing_for_exact_uic_v2(
        client,
        instrument=SaxoInstrument(asset="Natural Gas",uic=50419383,asset_type="ContractFutures"),
    )
    assert result == 60000002
    assert len(client.search_calls)==2
    assert client.search_calls[1]["Keywords"]=="Natural Gas"
    assert client.search_calls[1]["IncludeNonTradable"] is True


def test_unmatched_or_wrong_asset_candidate_is_never_selected():
    class SearchClient:
        def _get(self, path, params=None):
            return {"Data": [
                {"Identifier": 666, "PrimaryListing": 777,
                 "AssetType": "ContractFutures", "Description": "Natural Gas Oct 2026"},
                {"Identifier": 50419383, "PrimaryListing": 666,
                 "AssetType": "CfdOnFutures"}
            ]}
    candidate = discovery._search_primary_listing_for_exact_uic_v2(
        SearchClient(),
        instrument=SaxoInstrument(asset="Natural Gas",uic=50419383,asset_type="ContractFutures"),
    )
    assert candidate is None


def test_uic_search_failure_falls_back_to_nontradable_keyword_query():
    class ErrorClient(_Client):
        def _get(self, path, params=None):
            if "Uics" in params:
                self.search_calls.append(dict(params))
                raise RuntimeError("Saxo transient GET failed")
            return super()._get(path,params=params)
    client=ErrorClient()
    result=discovery._search_primary_listing_for_exact_uic_v2(
        client,
        instrument=SaxoInstrument(asset="Natural Gas",uic=50419383,asset_type="ContractFutures"),
    )
    assert result==60000002
    assert len(client.search_calls)==2



def test_successor_instrument_does_not_trigger_unnecessary_search():
    client = _Client()
    adapter = discovery._DiscoveryFallbackClientV2(
        client, now=datetime(2026, 9, 7, tzinfo=timezone.utc)
    )
    details = adapter.instrument_details(
        SaxoInstrument(asset="Natural Gas", uic=60000002, asset_type="ContractFutures")
    )
    assert details["IsTradable"] is True
    assert client.search_calls == []


def test_valid_contract_near_expiry_may_still_search_for_next():
    class NearExpiryClient(_Client):
        def instrument_details(self, instrument):
            if instrument.uic == 60000002:
                return {"IsTradable": True, "Uic":60000002,
                        "ExpiryDateTime":"2026-09-08T18:30:00Z",
                        "PrimaryListing":60000002}
            return super().instrument_details(instrument)
    client=NearExpiryClient()
    adapter=discovery._DiscoveryFallbackClientV2(
        client, now=datetime(2026, 9, 7, tzinfo=timezone.utc),
    )
    adapter.instrument_details(
        SaxoInstrument(asset="Natural Gas", uic=60000002, asset_type="ContractFutures")
    )
    assert client.search_calls
    assert client.search_calls[0]["Uics"]=="60000002"
