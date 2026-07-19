from __future__ import annotations

import unittest

from event_dna import build_event_dna, build_market_profile, event_similarity, find_similar_events
from event_models import MarketEvent


def event(event_id: str, title: str, *, country: str = "Iran", actors: list[str] | None = None) -> MarketEvent:
    return MarketEvent(
        event_id=event_id,
        source="test",
        event_date="2026-07-19",
        title=title,
        summary=title,
        category="conflict",
        subcategory="attack",
        domain="geopolitics",
        country=country,
        location="Strait of Hormuz",
        actors=actors or ["Iran"],
        confidence=0.9,
        market_sensitivity=0.8,
        significance=0.7,
        url="",
        raw={},
        published_at="2026-07-19T12:00:00Z",
        timestamp_source="test",
        timestamp_confidence=0.9,
    )


class EventDNATests(unittest.TestCase):
    def test_build_event_dna_extracts_type_target_and_normalises(self) -> None:
        dna = build_event_dna(event("a", "Iranian drone strike targets oil tanker"))
        self.assertEqual(dna.event_type, "attack")
        self.assertEqual(dna.target, "energy_infrastructure")
        self.assertEqual(dna.country, "iran")
        self.assertEqual(dna.actors, ("iran",))
        self.assertGreater(dna.severity, 0.7)

    def test_similarity_ranks_related_event_first(self) -> None:
        query = event("query", "Iranian missile attack on tanker in Strait of Hormuz")
        related = event("related", "Iran strikes tanker near Strait of Hormuz")
        unrelated = event("unrelated", "US inflation report shows lower producer prices", country="United States", actors=["Federal Reserve"])

        matches = find_similar_events(query, [unrelated, related], minimum_score=0.0)
        self.assertEqual(matches[0].event_id, "related")
        self.assertGreater(matches[0].score, matches[1].score)

    def test_similarity_is_symmetric(self) -> None:
        left = build_event_dna(event("left", "Drone strike on oil terminal"))
        right = build_event_dna(event("right", "Missile strike on refinery"))
        forward, _ = event_similarity(left, right)
        reverse, _ = event_similarity(right, left)
        self.assertEqual(forward, reverse)

    def test_market_profile_uses_only_matching_asset_and_events(self) -> None:
        query = event("query", "Attack on oil tanker")
        first = event("first", "Strike on tanker")
        second = event("second", "Drone attack on refinery")
        matches = find_similar_events(query, [first, second], minimum_score=0.0)
        reactions = [
            {"event_id": "first", "asset": "Brent", "return_1h_pct": 1.0, "return_4h_pct": 2.0, "return_24h_pct": 3.0, "quality_score": 0.9, "max_up_24h_pct": 4.0, "max_down_24h_pct": -0.5},
            {"event_id": "second", "asset": "Brent", "return_1h_pct": 0.5, "return_4h_pct": 1.0, "return_24h_pct": 1.5, "quality_score": 0.8, "max_up_24h_pct": 2.0, "max_down_24h_pct": -0.25},
            {"event_id": "first", "asset": "Silver", "return_1h_pct": -5.0, "quality_score": 1.0},
            {"event_id": "other", "asset": "Brent", "return_1h_pct": -10.0, "quality_score": 1.0},
        ]

        profile = build_market_profile(asset="Brent", similar_events=matches, reactions=reactions)
        self.assertEqual(profile.sample_size, 2)
        self.assertEqual(profile.direction, "LONG")
        self.assertEqual(profile.positive_share_pct, 100.0)
        self.assertAlmostEqual(profile.median_1h_pct or 0.0, 0.75)
        self.assertGreater(profile.confidence_pct, 0.0)


if __name__ == "__main__":
    unittest.main()
