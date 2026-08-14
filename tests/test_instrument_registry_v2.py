from __future__ import annotations

from contextlib import contextmanager

import instrument_registry_v2 as registry


def _sqlite_connect(tmp_path, monkeypatch):
    db_path = tmp_path / "instrument-registry-v2.db"

    @contextmanager
    def connect_for_test():
        from database import connect

        with connect(db_path, force_sqlite=True) as db:
            yield db

    monkeypatch.setattr(registry, "connect", connect_for_test)
    with connect_for_test() as db:
        db.executescript(
            """
            CREATE TABLE pg_v2_markets (
                market_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                category TEXT NOT NULL,
                base_currency TEXT,
                quote_currency TEXT,
                canonical_unit TEXT,
                active BOOLEAN NOT NULL DEFAULT TRUE
            );
            CREATE TABLE pg_v2_instruments (
                instrument_id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_id INTEGER NOT NULL,
                instrument_type TEXT NOT NULL,
                display_name TEXT NOT NULL,
                active BOOLEAN NOT NULL DEFAULT TRUE
            );
            CREATE TABLE pg_v2_instrument_sources (
                instrument_source_id INTEGER PRIMARY KEY AUTOINCREMENT,
                instrument_id INTEGER NOT NULL,
                provider TEXT NOT NULL,
                provider_instrument_id TEXT NOT NULL,
                asset_type TEXT,
                symbol TEXT,
                price_multiplier REAL,
                metadata_json TEXT,
                active BOOLEAN NOT NULL DEFAULT TRUE
            );
            CREATE TABLE pg_v2_collection_subscriptions (
                instrument_id INTEGER PRIMARY KEY,
                enabled BOOLEAN NOT NULL DEFAULT FALSE,
                resolution TEXT NOT NULL DEFAULT '1m',
                enabled_at TEXT,
                disabled_at TEXT
            );
            """
        )


def test_arbitrary_saxo_instrument_can_be_added_without_code_mapping(tmp_path, monkeypatch):
    _sqlite_connect(tmp_path, monkeypatch)

    market_id = registry.ensure_market_v2(
        name="Copper",
        category="commodity",
        quote_currency="USD",
        canonical_unit="price",
    )
    instrument_id = registry.ensure_instrument_v2(
        market_id=market_id,
        instrument_type="CFD",
        display_name="Copper CFD",
    )
    registry.ensure_instrument_source_v2(
        instrument_id=instrument_id,
        provider="SAXO",
        provider_instrument_id=987654321,
        asset_type="CfdOnFutures",
        symbol="COPPER",
        metadata={"exchange": "example", "description": "newly selected instrument"},
    )
    registry.set_collection_subscription_v2(instrument_id=instrument_id, enabled=True)

    resolved = registry.resolve_instrument_source_v2(
        provider="saxo",
        provider_instrument_id="987654321",
        require_subscription=True,
    )

    assert resolved.market_name == "Copper"
    assert resolved.provider_key == ("saxo", "987654321")
    assert resolved.asset_type == "CfdOnFutures"
    assert resolved.metadata["description"] == "newly selected instrument"


def test_registration_is_idempotent_for_same_market_instrument_and_source(tmp_path, monkeypatch):
    _sqlite_connect(tmp_path, monkeypatch)

    market_a = registry.ensure_market_v2(name="Custom Market", category="other")
    market_b = registry.ensure_market_v2(name="Custom Market", category="other")
    instrument_a = registry.ensure_instrument_v2(
        market_id=market_a,
        instrument_type="Stock",
        display_name="Example Share",
    )
    instrument_b = registry.ensure_instrument_v2(
        market_id=market_a,
        instrument_type="Stock",
        display_name="Example Share",
    )
    source_a = registry.ensure_instrument_source_v2(
        instrument_id=instrument_a,
        provider="saxo",
        provider_instrument_id="12345",
        asset_type="Stock",
    )
    source_b = registry.ensure_instrument_source_v2(
        instrument_id=instrument_a,
        provider="saxo",
        provider_instrument_id="12345",
        asset_type="Stock",
    )

    assert market_a == market_b
    assert instrument_a == instrument_b
    assert source_a == source_b


def test_subscription_controls_collection_without_deactivating_instrument(tmp_path, monkeypatch):
    _sqlite_connect(tmp_path, monkeypatch)

    market_id = registry.ensure_market_v2(name="Natural Gas", category="commodity")
    instrument_id = registry.ensure_instrument_v2(
        market_id=market_id,
        instrument_type="CFD",
        display_name="Natural Gas CFD",
    )
    registry.ensure_instrument_source_v2(
        instrument_id=instrument_id,
        provider="saxo",
        provider_instrument_id="555",
        asset_type="CfdOnFutures",
    )

    registry.set_collection_subscription_v2(instrument_id=instrument_id, enabled=True)
    assert len(registry.list_subscribed_sources_v2(provider="saxo")) == 1

    registry.set_collection_subscription_v2(instrument_id=instrument_id, enabled=False)
    assert registry.list_subscribed_sources_v2(provider="saxo") == ()

    resolved = registry.resolve_instrument_source_v2(provider="saxo", provider_instrument_id="555")
    assert resolved.instrument_id == instrument_id


def test_provider_identity_prevents_symbol_name_from_becoming_canonical_identity(tmp_path, monkeypatch):
    _sqlite_connect(tmp_path, monkeypatch)

    market_id = registry.ensure_market_v2(name="Gold", category="commodity")
    instrument_id = registry.ensure_instrument_v2(
        market_id=market_id,
        instrument_type="CFD",
        display_name="Gold spot CFD",
    )
    registry.ensure_instrument_source_v2(
        instrument_id=instrument_id,
        provider="saxo",
        provider_instrument_id="42",
        asset_type="CfdOnIndex",
        symbol="GOLD",
    )

    source = registry.resolve_instrument_source_v2(provider="saxo", provider_instrument_id="42")
    assert source.provider_instrument_id == "42"
    assert source.symbol == "GOLD"
