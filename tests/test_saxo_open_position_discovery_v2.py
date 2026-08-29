from __future__ import annotations

from types import SimpleNamespace

import pytest

import runtime_subscription_bridge_v2 as bridge_v2
import saxo_open_position_discovery_v2 as discovery_v2
from instrument_onboarding_v2 import InstrumentOnboardingResultV2
from instrument_registry_v2 import InstrumentSourceV2
from saxo_provider import SaxoInstrument


def _position(*, account_id: str = "ACC-1", uic: int = 4912, asset_type: str = "CfdOnIndex"):
    return SimpleNamespace(account_id=account_id, uic=uic, asset_type=asset_type)


def _source(
    *,
    uic: int = 4912,
    asset_type: str = "CfdOnIndex",
    market_id: int = 7,
    instrument_id: int = 9,
    market_name: str = "US Tech 100 NAS · Saxo 4912",
) -> InstrumentSourceV2:
    return InstrumentSourceV2(
        market_id=market_id,
        market_name=market_name,
        instrument_id=instrument_id,
        instrument_type=asset_type,
        display_name=f"{market_name} [{asset_type}:{uic}]",
        provider="saxo",
        provider_instrument_id=str(uic),
        asset_type=asset_type,
        symbol="USTECH",
        price_multiplier=1.0,
        metadata={"description": "US Tech 100 NAS"},
    )


class _ReferenceClient:
    def __init__(self, *, uic: int = 4912, asset_type: str = "CfdOnIndex") -> None:
        self.uic = uic
        self.asset_type = asset_type
        self.calls: list[tuple[str, dict | None]] = []

    def _get(self, path: str, params=None):
        self.calls.append((path, params))
        if path == "port/v1/accounts/me":
            return {
                "Data": [
                    {"AccountId": "ACC-1", "AccountKey": "KEY-1", "Active": True},
                ]
            }
        if path == f"ref/v1/instruments/details/4912/CfdOnIndex":
            return {
                "Uic": self.uic,
                "AssetType": self.asset_type,
                "Description": "US Tech 100 NAS",
                "Symbol": "USTECH",
                "CurrencyCode": "USD",
                "UnderlyingAssetType": "StockIndex",
                "TradableAs": ["CfdOnIndex"],
                "Exchange": {"Name": "Saxo CFD"},
            }
        raise AssertionError(f"unexpected GET {path}")


def test_unknown_open_position_uses_exact_reference_identity_and_onboards(monkeypatch):
    client = _ReferenceClient()
    monkeypatch.setattr(discovery_v2, "using_postgres", lambda: True)
    monkeypatch.setattr(discovery_v2, "_position_observations_v2", lambda _client: (_position(),))
    monkeypatch.setattr(discovery_v2, "_subscribed_source", lambda _uic: None)
    monkeypatch.setattr(discovery_v2, "_existing_source", lambda _uic: None)

    captured = {}

    def _onboard(product, reference):
        captured["product"] = product
        captured["reference"] = reference
        return InstrumentOnboardingResultV2(
            market_id=7,
            instrument_id=9,
            instrument_source_id=11,
            market_name=discovery_v2._market_name(reference),
            market_category="cfd",
            display_name=discovery_v2._display_name(reference),
            provider="saxo",
            provider_instrument_id="4912",
            asset_type="CfdOnIndex",
            subscription_enabled=True,
            reused_existing_source=False,
        )

    monkeypatch.setattr(discovery_v2, "_onboard_reference", _onboard)

    summary = discovery_v2.discover_open_saxo_positions_once_v2(client)

    assert summary.observed_products == 1
    assert summary.onboarded == 1
    assert summary.failed == 0
    assert captured["reference"].uic == 4912
    assert captured["reference"].asset_type == "CfdOnIndex"
    assert captured["reference"].description == "US Tech 100 NAS"
    assert discovery_v2._market_name(captured["reference"]) == "US Tech 100 NAS · Saxo 4912"
    assert (
        "ref/v1/instruments/details/4912/CfdOnIndex",
        {"AccountKey": "KEY-1", "FieldGroups": "OrderSetting"},
    ) in client.calls


def test_reference_data_identity_mismatch_fails_closed(monkeypatch):
    client = _ReferenceClient(uic=9999)
    product = discovery_v2.SaxoOpenPositionIdentityV2(
        account_id="ACC-1",
        uic=4912,
        asset_type="CfdOnIndex",
    )
    with pytest.raises(ValueError, match="did not match the open position"):
        discovery_v2._load_reference_identity(
            client,
            product=product,
            account_key="KEY-1",
        )


def test_already_subscribed_position_is_idempotent_and_skips_reference_lookup(monkeypatch):
    monkeypatch.setattr(discovery_v2, "using_postgres", lambda: True)
    monkeypatch.setattr(discovery_v2, "_position_observations_v2", lambda _client: (_position(), _position()))
    monkeypatch.setattr(discovery_v2, "_subscribed_source", lambda _uic: _source())
    monkeypatch.setattr(
        discovery_v2,
        "_account_keys",
        lambda _client: (_ for _ in ()).throw(AssertionError("account lookup should not occur")),
    )

    summary = discovery_v2.discover_open_saxo_positions_once_v2(object())

    assert summary.observed_products == 1
    assert summary.already_subscribed == 1
    assert summary.onboarded == 0
    assert summary.failed == 0


def test_reactivating_source_never_replaces_another_active_market_feed(monkeypatch):
    source = _source(instrument_id=9)
    conflicting = _source(uic=36590, instrument_id=10, market_name=source.market_name)
    monkeypatch.setattr(discovery_v2, "list_subscribed_sources_v2", lambda **_kwargs: (conflicting,))
    monkeypatch.setattr(
        discovery_v2,
        "set_collection_subscription_v2",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must not replace active feed")),
    )

    with pytest.raises(ValueError, match="different active Saxo feed"):
        discovery_v2._reactivate_existing_source(source, asset_type="CfdOnIndex")


def test_registry_refresh_survives_discovery_outage(monkeypatch):
    configured = {
        "Gold": SaxoInstrument(asset="Gold", uic=123, asset_type="ContractFutures"),
    }
    monkeypatch.setattr(
        bridge_v2,
        "discover_open_saxo_positions_once_v2",
        lambda: (_ for _ in ()).throw(RuntimeError("temporary Saxo timeout")),
    )
    monkeypatch.setattr(bridge_v2, "list_subscribed_sources_v2", lambda **_kwargs: ())

    result = bridge_v2.load_runtime_instruments_v2(configured)

    assert result.instruments == configured
    assert result.registry_markets == ()
