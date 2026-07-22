from datetime import datetime, timezone

from asset_state_mapping import AssetRecommendation
from market_interpretation import MarketInterpretation
from signal_outcomes import SignalOutcomeStore, register_recommendations


def _interpretation():
    return MarketInterpretation.from_mapping(
        {
            "event_id": "telegram:test:outcome",
            "cluster_id": "cluster:test",
            "published_at": "2026-07-22T12:00:00+00:00",
            "summary": "test",
            "state_deltas": {
                "conflict_pressure": 0.1,
                "energy_supply_risk": 0.0,
                "shipping_risk": 0.0,
                "safe_haven_pressure": 0.1,
                "usd_pressure": 0.0,
            },
            "novelty": 0.8,
            "confidence": 0.8,
            "source_quality": 0.8,
            "update_type": "NEW_EVENT",
            "model_version": "test-model",
            "prompt_version": "test-prompt",
        }
    )


def test_register_recommendation_is_idempotent(tmp_path):
    store = SignalOutcomeStore(tmp_path / "outcomes.db")
    recommendation = AssetRecommendation("Gold", "LONG", 0.2, 20, 4, ("driver",))
    created_at = datetime(2026, 7, 22, 12, 5, tzinfo=timezone.utc)
    first = register_recommendations(_interpretation(), [recommendation], store=store, created_at=created_at)
    second = register_recommendations(_interpretation(), [recommendation], store=store, created_at=created_at)
    assert first[0].signal_id == second[0].signal_id
    assert len(store.load_all()) == 1
