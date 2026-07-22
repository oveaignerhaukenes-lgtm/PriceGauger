from datetime import datetime, timezone

from event_resolution import CanonicalEvent, EventFacts
from market_interpreter import MockMarketInterpreter
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


def test_mock_interpreter_is_deterministic():
    interpreter = MockMarketInterpreter()
    first = interpreter.interpret(_event())
    second = interpreter.interpret(_event())
    assert first.to_record() == second.to_record()
    assert first.state_deltas["energy_supply_risk"] > 0


def test_duplicate_produces_zero_deltas():
    interpretation = MockMarketInterpreter().interpret(_event(), update_type="DUPLICATE")
    assert interpretation.novelty == 0.0
    assert all(value == 0.0 for value in interpretation.state_deltas.values())


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
