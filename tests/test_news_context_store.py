from datetime import datetime, timezone

from news_context_engine import NewsContextAssessment, NewsWindow
from news_context_store import NewsContextStore
from telegram_query_builder import TelegramSearchPlan


NOW = "2026-08-07T20:00:00+00:00"


def _assessment() -> NewsContextAssessment:
    return NewsContextAssessment(
        as_of=NOW,
        engine_version="news-context-v1",
        source_channel="Middle_East_Spectator",
        source_post_count=1,
        coverage_start="2026-08-07T19:00:00+00:00",
        coverage_end="2026-08-07T19:00:00+00:00",
        coverage_warning="",
        conflict_level=0.8,
        fear_level=0.7,
        escalation_direction="escalating",
        physical_supply_risk=0.6,
        narrative_saturation=0.4,
        confirmation_quality=0.75,
        regime_label="elevated escalation",
        active_drivers=("shipping risk",),
        counter_signals=(),
        unresolved_questions=("closure confirmed?",),
        summary="Elevated but not yet physically confirmed.",
        confidence=0.7,
        model="test-model",
        windows=(NewsWindow(1, 1, NOW, NOW, ("update",)),),
    )


def _plan() -> TelegramSearchPlan:
    return TelegramSearchPlan(
        message_id="1",
        message_url="https://t.me/example/1",
        message_text="update",
        event_type="event",
        target="unspecified",
        country="",
        domain="",
        search="event context",
        signal_score=2,
        published_at="2026-08-07T19:00:00+00:00",
    )


def test_news_context_round_trip_and_refresh_policy(tmp_path):
    store = NewsContextStore(tmp_path / "context.sqlite3")
    store.save(_assessment())

    loaded = store.load_latest()

    assert loaded == _assessment()
    assert store.should_refresh(
        [_plan()], now=datetime(2026, 8, 7, 20, 5, tzinfo=timezone.utc)
    ) is False
    assert store.should_refresh(
        [_plan()], now=datetime(2026, 8, 7, 20, 16, tzinfo=timezone.utc)
    ) is True
