from datetime import datetime, timezone

import pytest

from asset_state_mapping import build_asset_recommendation
from market_interpretation import MarketInterpretation
from market_state import build_market_state
from market_state_store import MarketStateStore


def item(**overrides):
    payload = {
        "event_id": "telegram:1",
        "cluster_id": "cluster:a",
        "published_at": "2026-07-22T00:00:00+00:00",
        "summary": "Attack on oil terminal",
        "state_deltas": {
            "conflict_pressure": 0.3,
            "energy_supply_risk": 0.7,
            "shipping_risk": 0.1,
            "safe_haven_pressure": 0.2,
            "usd_pressure": 0.0,
        },
        "novelty": 1.0,
        "confidence": 1.0,
        "source_quality": 1.0,
        "update_type": "NEW_EVENT",
    }
    payload.update(overrides)
    return MarketInterpretation.from_mapping(payload)


def test_schema_rejects_unknown_state():
    payload = item().to_record()
    payload["state_deltas"]["invented_state"] = 0.2
    with pytest.raises(ValueError):
        MarketInterpretation.from_mapping(payload)


def test_duplicate_contributes_nothing():
    duplicate = item(update_type="DUPLICATE")
    state = build_market_state(
        [duplicate],
        as_of="2026-07-22T00:10:00+00:00",
    )
    assert all(value == 0.0 for value in state.values.values())


def test_decay_reduces_contribution():
    event = item()
    early = build_market_state(
        [event],
        as_of="2026-07-22T00:10:00+00:00",
    )
    late = build_market_state(
        [event],
        as_of="2026-07-22T03:00:00+00:00",
    )
    assert early.values["energy_supply_risk"] > late.values["energy_supply_risk"] > 0


def test_brent_responds_long_to_energy_risk_change():
    state = build_market_state(
        [item()],
        as_of="2026-07-22T00:10:00+00:00",
    )
    recommendation = build_asset_recommendation("Brent", state)
    assert recommendation.direction == "LONG"
    assert recommendation.signal_strength > 10


def test_store_round_trip(tmp_path):
    store = MarketStateStore(tmp_path / "state.db")
    original = item()
    store.save_interpretation(original)
    loaded = store.load_interpretations()
    assert loaded == [original]
