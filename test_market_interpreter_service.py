from datetime import datetime, timezone

from event_resolution import CanonicalEvent, EventFacts
from market_interpreter import MockMarketInterpreter, StructuredMarketInterpreter
from market_state_service import process_market_event
from market_state_store import MarketStateStore


def _event(text="Missile strike hit an oil terminal"):
    return CanonicalEvent(
        event_id="telegram:test:1",
        cluster_id="cluster:test",
        source_message_id="1",
        source_url="https://t.me/test/1",
        title=text,
        event_type="attack",
        target="energy_infrastructure",
        country="Bahrain",
        domain="",
        published_at="2026-07-22T00:00:00+00:00",
        relevance_score=0.9,
        facts=EventFacts(),
    )


class FakeProvider:
    model_version = "fake-model-v1"

    def complete_json(self, *, system_prompt, user_payload):
        assert "Do not recommend a trade" in system_prompt
        assert "Do not invent" in system_prompt
        assert user_payload["event_id"] == "telegram:test:1"
        return {
            "summary": "Reported strike on an oil terminal",
            "state_deltas": {
                "conflict_pressure": 0.2,
                "energy_supply_risk": 0.5,
                "shipping_risk": 0.0,
                "safe_haven_pressure": 0.1,
                "usd_pressure": 0.0,
            },
            "novelty": 0.8,
            "confidence": 0.7,
            "source_quality": 0.6,
            "evidence": ["Missile strike hit an oil terminal"],
            "uncertainties": ["Damage is not confirmed"],
        }


def test_mock_interpreter_is_deterministic():
    interpreter = MockMarketInterpreter()
    first = interpreter.interpret(_event())
    second = interpreter.interpret(_event())
    assert first.to_record() == second.to_record()
    assert first.state_deltas["energy_supply_risk"] > 0


def test_structured_interpreter_uses_canonical_metadata():
    item = StructuredMarketInterpreter(FakeProvider()).interpret(_event())
    assert item.event_id == "telegram:test:1"
    assert item.cluster_id == "cluster:test"
    assert item.model_version == "fake-model-v1"
    assert item.state_deltas["energy_supply_risk"] == 0.5


def test_service_persists_once_and_builds_recommendations(tmp_path):
    store = MarketStateStore(tmp_path / "state.db")
    now = datetime(2026, 7, 22, 0, 15, tzinfo=timezone.utc)
    first = process_market_event(_event(), store=store, as_of=now)
    second = process_market_event(_event(), store=store, as_of=now)
    assert first.created is True
    assert second.created is False
    assert len(store.load_interpretations()) == 1
    assert {item.asset for item in first.recommendations} == {"Brent", "Gold", "Silver", "DXY"}
    brent = next(item for item in first.recommendations if item.asset == "Brent")
    assert brent.direction == "LONG"


def test_service_refreshes_when_model_changes(tmp_path):
    store = MarketStateStore(tmp_path / "state.db")
    now = datetime(2026, 7, 22, 0, 15, tzinfo=timezone.utc)
    process_market_event(_event(), store=store, as_of=now)
    result = process_market_event(
        _event(),
        store=store,
        as_of=now,
        interpreter=StructuredMarketInterpreter(FakeProvider()),
    )
    assert result.created is False
    assert result.interpretation.model_version == "fake-model-v1"
    assert store.load_interpretations()[0].model_version == "fake-model-v1"
