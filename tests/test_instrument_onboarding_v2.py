from __future__ import annotations

from contextlib import contextmanager

import pytest

import instrument_onboarding_v2 as onboarding


def _connect_for_test(tmp_path, monkeypatch, *, broken_subscription: bool = False):
    db_path = tmp_path / "onboarding-v2.db"

    @contextmanager
    def connect_test():
        from database import connect

        with connect(db_path, force_sqlite=True) as db:
            yield db

    monkeypatch.setattr(onboarding, "connect", connect_test)
    resolution_check = "CHECK (resolution = '5m')" if broken_subscription else "CHECK (resolution = '1m')"
    with connect_test() as db:
        db.executescript(
            f"""
            CREATE TABLE pg_v2_markets (
                market_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                category TEXT NOT NULL,
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
                active BOOLEAN NOT NULL DEFAULT TRUE,
                UNIQUE(provider, provider_instrument_id)
            );
            CREATE TABLE pg_v2_collection_subscriptions (
                instrument_id INTEGER PRIMARY KEY,
                enabled BOOLEAN NOT NULL DEFAULT FALSE,
                resolution TEXT NOT NULL DEFAULT '1m' {resolution_check},
                enabled_at TEXT,
                disabled_at TEXT
            );
            """
        )
    return connect_test


def _request(**overrides):
    values = {
        "market_name": "Gold",
        "market_category": "commodity",
        "display_name": "Gold Mini Long",
        "uic": 123456,
        "asset_type": "MiniFuture",
        "symbol": "MINI L GOLD",
        "price_multiplier": 1.0,
        "metadata": {"description": "Gold Mini Long", "exchange": "Saxo"},
    }
    values.update(overrides)
    return onboarding.SaxoInstrumentOnboardingRequestV2(**values)


def test_onboarding_atomically_creates_registry_source_and_subscription(tmp_path, monkeypatch) -> None:
    connect_test = _connect_for_test(tmp_path, monkeypatch)

    result = onboarding.onboard_saxo_instrument_v2(_request())

    assert result.market_name == "Gold"
    assert result.market_category == "commodity"
    assert result.asset_type == "MiniFuture"
    assert result.provider == "saxo"
    assert result.provider_instrument_id == "123456"
    assert result.subscription_enabled is True
    assert result.reused_existing_source is False

    with connect_test() as db:
        assert db.execute("SELECT COUNT(*) FROM pg_v2_markets").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM pg_v2_instruments").fetchone()[0] == 1
        source = db.execute(
            "SELECT provider_instrument_id, asset_type, symbol FROM pg_v2_instrument_sources"
        ).fetchone()
        assert tuple(source) == ("123456", "MiniFuture", "MINI L GOLD")
        subscription = db.execute(
            "SELECT enabled, resolution FROM pg_v2_collection_subscriptions"
        ).fetchone()
        assert bool(subscription[0]) is True
        assert subscription[1] == "1m"


def test_existing_saxo_source_is_reused_without_silent_market_remap(tmp_path, monkeypatch) -> None:
    connect_test = _connect_for_test(tmp_path, monkeypatch)
    first = onboarding.onboard_saxo_instrument_v2(_request())

    second = onboarding.onboard_saxo_instrument_v2(
        _request(market_name="Not Gold", market_category="other", display_name="Different label")
    )

    assert second.reused_existing_source is True
    assert second.market_id == first.market_id
    assert second.instrument_id == first.instrument_id
    assert second.market_name == "Gold"
    assert second.display_name == "Gold Mini Long"
    with connect_test() as db:
        assert db.execute("SELECT COUNT(*) FROM pg_v2_markets").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM pg_v2_instruments").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM pg_v2_instrument_sources").fetchone()[0] == 1


def test_existing_provider_identity_with_different_asset_type_fails_closed(tmp_path, monkeypatch) -> None:
    _connect_for_test(tmp_path, monkeypatch)
    onboarding.onboard_saxo_instrument_v2(_request())

    with pytest.raises(ValueError, match="different AssetType"):
        onboarding.onboard_saxo_instrument_v2(_request(asset_type="Warrant"))


def test_existing_market_category_cannot_be_silently_changed(tmp_path, monkeypatch) -> None:
    connect_test = _connect_for_test(tmp_path, monkeypatch)
    onboarding.onboard_saxo_instrument_v2(_request())

    with pytest.raises(ValueError, match="refusing silent semantic change"):
        onboarding.onboard_saxo_instrument_v2(
            _request(uic=999999, market_category="equity", display_name="Other instrument")
        )

    with connect_test() as db:
        assert db.execute("SELECT COUNT(*) FROM pg_v2_instrument_sources").fetchone()[0] == 1


def test_subscription_failure_rolls_back_new_market_instrument_and_source(tmp_path, monkeypatch) -> None:
    connect_test = _connect_for_test(tmp_path, monkeypatch, broken_subscription=True)

    with pytest.raises(Exception):
        onboarding.onboard_saxo_instrument_v2(_request())

    with connect_test() as db:
        assert db.execute("SELECT COUNT(*) FROM pg_v2_markets").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM pg_v2_instruments").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM pg_v2_instrument_sources").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM pg_v2_collection_subscriptions").fetchone()[0] == 0


def test_request_validation_happens_before_registry_write(tmp_path, monkeypatch) -> None:
    connect_test = _connect_for_test(tmp_path, monkeypatch)

    with pytest.raises(ValueError, match="market_name"):
        onboarding.onboard_saxo_instrument_v2(_request(market_name=""))

    with connect_test() as db:
        assert db.execute("SELECT COUNT(*) FROM pg_v2_markets").fetchone()[0] == 0
