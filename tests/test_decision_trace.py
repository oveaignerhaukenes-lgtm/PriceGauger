from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import storage
from decision_trace import (
    build_decision_trace,
    load_decision_trace,
    save_decision_trace,
    update_decision_outcome,
)
from event_dna import build_event_dna, build_market_profile, find_similar_events
from event_models import MarketEvent


def event(event_id: str, title: str) -> MarketEvent:
    return MarketEvent(
        event_id=event_id,
        source="test",
        event_date="2026-07-19",
        title=title,
        summary=title,
        category="conflict",
        subcategory="attack",
        domain="geopolitics",
        country="Iran",
        location="Strait of Hormuz",
        actors=["Iran"],
        confidence=0.9,
        market_sensitivity=0.8,
        significance=0.7,
        url="",
        raw={},
        published_at="2026-07-19T12:00:00Z",
        timestamp_source="test",
        timestamp_confidence=0.9,
    )


class DecisionTraceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db_path = storage.DB_PATH
        storage.DB_PATH = Path(self.tempdir.name) / "trace.db"

    def tearDown(self) -> None:
        storage.DB_PATH = self.original_db_path
        self.tempdir.cleanup()

    def test_trace_round_trip_and_outcome_update(self) -> None:
        query = event("query", "Iran attacks oil tanker")
        historical = event("historical", "Strike on tanker near Hormuz")
        matches = find_similar_events(query, [historical], minimum_score=0.0)
        profile = build_market_profile(
            asset="Brent",
            similar_events=matches,
            reactions=[
                {
                    "event_id": "historical",
                    "asset": "Brent",
                    "return_1h_pct": 1.0,
                    "return_4h_pct": 2.0,
                    "quality_score": 0.9,
                }
            ],
        )
        trace = build_decision_trace(
            event=query,
            event_dna=build_event_dna(query),
            similar_events=matches,
            market_profile=profile,
            assessment={"direction": "LONG", "confidence_pct": 72.0},
            strategy={"action": "LONG", "max_leverage": 4.0},
            trace_id="trace-1",
            created_at="2026-07-19T12:01:00+00:00",
        )

        save_decision_trace(trace)
        loaded = load_decision_trace("trace-1")

        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.event_id, "query")
        self.assertEqual(loaded.asset, "Brent")
        self.assertEqual(loaded.event_dna["event_type"], "attack")
        self.assertEqual(len(loaded.similar_events), 1)
        self.assertEqual(loaded.assessment["direction"], "LONG")
        self.assertIsNone(loaded.outcome)

        changed = update_decision_outcome(
            "trace-1",
            {"return_1h_pct": 0.8, "return_4h_pct": 1.5, "result": "correct"},
        )
        updated = load_decision_trace("trace-1")

        self.assertTrue(changed)
        assert updated is not None
        self.assertEqual(updated.outcome["result"], "correct")
        self.assertEqual(updated.outcome["return_1h_pct"], 0.8)

    def test_missing_trace_returns_none(self) -> None:
        self.assertIsNone(load_decision_trace("missing"))
        self.assertFalse(update_decision_outcome("missing", {"result": "unknown"}))


if __name__ == "__main__":
    unittest.main()
