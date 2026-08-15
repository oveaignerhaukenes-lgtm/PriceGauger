from __future__ import annotations

from dataclasses import dataclass

import live_technical_runtime_v2 as runtime
from recipe_registry_v2 import TA_ONLY_V1, TECHNICAL_CORE_RECIPE_V2_1
from saxo_provider import SaxoInstrument


def _instrument(asset: str, uic: int) -> SaxoInstrument:
    return SaxoInstrument(
        asset=asset,
        uic=uic,
        asset_type="CfdOnFutures",
        symbol=asset,
        description=f"{asset} future",
        expiry="2026-12-01",
        price_multiplier=1.0,
    )


def test_register_saxo_instrument_uses_generic_v2_registry(monkeypatch):
    calls = []
    monkeypatch.setattr(runtime, "ensure_market_v2", lambda **kwargs: calls.append(("market", kwargs)) or 7)
    monkeypatch.setattr(runtime, "ensure_instrument_v2", lambda **kwargs: calls.append(("instrument", kwargs)) or 11)
    monkeypatch.setattr(runtime, "ensure_instrument_source_v2", lambda **kwargs: calls.append(("source", kwargs)) or 13)
    monkeypatch.setattr(runtime, "set_collection_subscription_v2", lambda **kwargs: calls.append(("subscription", kwargs)))

    market_id = runtime.register_saxo_instrument_v2(
        market="Gold",
        instrument=_instrument("GOLD", 42),
    )

    assert market_id == 7
    source = next(payload for kind, payload in calls if kind == "source")
    assert source["provider"] == "saxo"
    assert source["provider_instrument_id"] == "42"
    assert source["instrument_id"] == 11
    subscription = next(payload for kind, payload in calls if kind == "subscription")
    assert subscription == {"instrument_id": 11, "enabled": True}


def test_live_cycle_persists_canonical_ta_only_recipe_and_isolates_market_failure(monkeypatch):
    monkeypatch.setattr(runtime, "ensure_db_v2_schema", lambda: None)
    monkeypatch.setattr(runtime, "MarketHistoryStore", lambda path: object())

    market_ids = {"Gold": 1, "Silver": 2}
    monkeypatch.setattr(
        runtime,
        "register_saxo_instrument_v2",
        lambda *, market, instrument: market_ids[market],
    )

    @dataclass
    class Produced:
        as_of: str

    def produce(*, market, history_store):
        if market == "Silver":
            raise LookupError("not enough canonical history")
        return Produced(as_of="2026-08-15T08:00:00+00:00")

    persisted = []
    health = []
    monkeypatch.setattr(runtime, "produce_technical_runtime_v2", produce)
    monkeypatch.setattr(runtime, "persist_produced_runtime_v2", lambda produced, **kwargs: persisted.append(kwargs))
    monkeypatch.setattr(runtime, "record_runtime_health_v2", lambda item: health.append(item))
    monkeypatch.setattr(
        runtime,
        "freshness_health_v2",
        lambda **kwargs: ("fresh", kwargs),
    )

    summary = runtime.run_live_technical_cycle_v2(
        instruments={
            "Gold": _instrument("GOLD", 42),
            "Silver": _instrument("SILVER", 43),
        }
    )

    assert summary.attempted == 2
    assert summary.produced == 1
    assert summary.failed == 1
    assert persisted == [
        {
            "market_id": 1,
            "technical_recipe_id": TECHNICAL_CORE_RECIPE_V2_1.recipe_id,
            "analysis_recipe_id": TA_ONLY_V1.recipe_id,
            "analysis_recipe_name": TA_ONLY_V1.name,
            "analysis_recipe_version": TA_ONLY_V1.version,
        }
    ]
    assert any(getattr(item, "status", None) == "DEGRADED" for item in health)


def test_ensure_db_v2_schema_is_postgres_only(monkeypatch):
    monkeypatch.setattr(runtime, "using_postgres", lambda: False)

    try:
        runtime.ensure_db_v2_schema()
    except RuntimeError as exc:
        assert "requires PostgreSQL" in str(exc)
    else:
        raise AssertionError("SQLite must not define live DB v2 runtime semantics")
