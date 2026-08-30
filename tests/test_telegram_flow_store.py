from __future__ import annotations

import inspect

import pytest

import telegram_flow_store
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


def _assessment(store: TelegramFlowStore):
    posts = [
        _post("1", "2026-07-29T10:00:00+00:00", 1.0),
        _post("2", "2026-07-29T10:30:00+00:00", -0.5),
    ]
    assert store.save_posts(posts) == 2
    return aggregate_scored_posts(store.load_posts(), as_of="2026-07-29T11:00:00+00:00")


def test_store_round_trips_posts_and_latest_snapshot(tmp_path):
    store = TelegramFlowStore(tmp_path / "flow.sqlite3")
    assessment = _assessment(store)

    store.save_snapshot(assessment)
    restored = store.load_latest_snapshot()

    assert restored is not None
    assert restored.as_of == assessment.as_of
    assert restored.post_count == 2
    assert restored.assets[0].asset == "Brent"
    assert restored.contributions[0].rationale == "causal test"


def test_store_rejects_retired_legacy_save_and_process_path(tmp_path):
    store = TelegramFlowStore(tmp_path / "flow.sqlite3")
    assessment = _assessment(store)

    with pytest.raises(ValueError, match="legacy Telegram save-and-process runtime is retired"):
        store.save_snapshot(assessment, process_runtime=True)

    assert store.load_latest_snapshot() is None


def test_store_source_has_no_retired_state_runtime_import():
    source = inspect.getsource(telegram_flow_store)
    assert "state_runtime_pipeline" not in source
    assert "process_flow_snapshot" not in source
    assert 'process_runtime: bool = False' in source
