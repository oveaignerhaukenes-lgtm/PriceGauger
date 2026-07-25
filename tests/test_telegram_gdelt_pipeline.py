from datetime import datetime, timezone

from event_models import MarketEvent
from gdelt_candidate_store import load_gdelt_candidates
from gdelt_types import GdeltPage
from telegram_gdelt_pipeline import (
    gdelt_request_from_telegram_plan,
    ingest_telegram_plan_to_gdelt,
)
from telegram_query_builder import TelegramSearchPlan


class FakeGdeltProvider:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def list_events(self, **kwargs):
        self.calls.append(kwargs)
        return GdeltPage(
            events=[
                MarketEvent(
                    event_id="gdelt-doc:test-telegram-1",
                    source="gdelt_doc_v2",
                    event_date="2025-03-10",
                    title="Pipeline disruption affects exports",
                    summary="Pipeline disruption affects exports",
                    category="news_coverage",
                    subcategory="article",
                    domain="example.com",
                    country="Iran",
                    location="",
                    actors=[],
                    confidence=None,
                    market_sensitivity=None,
                    significance=None,
                    url="https://example.com/pipeline",
                    raw={"seendate": "20250310120000"},
                    published_at="2025-03-10T12:00:00+00:00",
                    timestamp_source="gdelt:seendate",
                    timestamp_confidence=0.85,
                )
            ],
            next_cursor=None,
        )


def sample_plan() -> TelegramSearchPlan:
    return TelegramSearchPlan(
        message_id="12345",
        message_url="https://t.me/Middle_East_Spectator/12345",
        message_text="Iran pipeline disrupted after attack",
        event_type="attack",
        target="energy infrastructure",
        country="Iran",
        domain="INFRASTRUCTURE",
        search="attack energy infrastructure Iran",
        signal_score=3,
        published_at="2026-07-25T12:00:00+00:00",
    )


def test_telegram_plan_translates_without_hidden_date_policy():
    request = gdelt_request_from_telegram_plan(
        sample_plan(),
        date_start="2023-01-01",
        date_end="2026-07-24",
        limit=30,
    )

    assert request.search == "attack energy infrastructure Iran"
    assert request.country == "Iran"
    assert request.date_start == "2023-01-01"
    assert request.date_end == "2026-07-24"
    assert request.limit == 30


def test_telegram_plan_ingests_and_persists_candidates(tmp_path):
    provider = FakeGdeltProvider()
    result = ingest_telegram_plan_to_gdelt(
        sample_plan(),
        provider,
        provider_name="GDELT DOC",
        date_start="2023-01-01",
        date_end="2026-07-24",
        limit=30,
        database_path=tmp_path / "pricegauger.db",
        retrieved_at=datetime(2026, 7, 25, 13, 0, tzinfo=timezone.utc),
    )

    assert result.message_id == "12345"
    assert result.candidate_count == 1
    assert result.saved_count == 1
    assert result.warning is None
    assert len(result.candidates) == 1

    loaded = load_gdelt_candidates(
        result.search_id,
        database_path=tmp_path / "pricegauger.db",
    )
    assert list(result.candidates) == loaded
    assert provider.calls == [
        {
            "date_start": "2023-01-01",
            "date_end": "2026-07-24",
            "search": "attack energy infrastructure Iran",
            "country": "Iran",
            "domain": "",
            "confidence_profile": "precise",
            "sort": "significance",
            "limit": 30,
        }
    ]
