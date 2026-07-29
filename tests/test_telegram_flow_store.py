from __future__ import annotations

from telegram_flow_engine import (
    AssetPostScore,
    ScoredTelegramPost,
    aggregate_scored_posts,
)
from telegram_flow_store import TelegramFlowStore


def _post(message_id: str, published_at: str, direction: float) -> ScoredTelegramPost:
    return ScoredTelegramPost(
        message_id=message_id,
        channel="Middle_East_Spectator",
        published_at=published_at,
        text="test event",
        event_key=f"event-{message_id}",
        relation="new",
        novelty=1.0,
        source_quality=1.0,
        scores=(
            AssetPostScore(
                asset="Brent",
                direction=direction,
                impact=0.8,
                confidence=0.9,
                horizon_hours=4.0,
                rationale="causal test",
            ),
        ),
    )


def test_store_round_trips_posts_and_latest_snapshot(tmp_path):
    store = TelegramFlowStore(tmp_path / "flow.sqlite3")
    posts = [
        _post("1", "2026-07-29T10:00:00+00:00", 1.0),
        _post("2", "2026-07-29T10:30:00+00:00", -0.5),
    ]

    assert store.save_posts(posts) == 2
    assert store.has_post("1") is True
    loaded = store.load_posts()
    assert [item.message_id for item in loaded] == ["1", "2"]

    assessment = aggregate_scored_posts(loaded, as_of="2026-07-29T11:00:00+00:00")
    store.save_snapshot(assessment)
    restored = store.load_latest_snapshot()

    assert restored is not None
    assert restored.as_of == assessment.as_of
    assert restored.post_count == 2
    assert restored.assets[0].asset == "Brent"
    assert restored.contributions[0].rationale == "causal test"
