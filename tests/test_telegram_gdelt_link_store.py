from datetime import datetime, timezone

from event_models import MarketEvent
from gdelt_candidate_store import load_gdelt_candidates
from gdelt_types import GdeltPage
from telegram_gdelt_link_store import load_telegram_gdelt_search_links
from telegram_gdelt_pipeline import ingest_telegram_plan_to_gdelt
from telegram_query_builder import TelegramSearchPlan


class FakeGdeltProvider:
    def list_events(self, **kwargs):
        return GdeltPage(
            events=[
                MarketEvent(
                    event_id="gdelt-doc:linked-test",
                    source="gdelt_doc_v2",
                    event_date="2026-07-20",
                    title="Oil terminal disrupted after attack",
                    summary="Oil terminal disrupted after attack",
                    category="news_coverage",
                    subcategory="article",
                    domain="example.com",
                    country="Iran",
                    location="",
                    actors=[],
                    confidence=None,
                    market_sensitivity=None,
                    significance=None,
                    url="https://example.com/linked-test",
                    raw={"seendate": "20260720T120000Z"},
                    published_at="2026-07-20T12:00:00+00:00",
                    timestamp_source="gdelt:seendate",
                    timestamp_confidence=0.85,
                )
            ],
            next_cursor=None,
        )


def sample_plan() -> TelegramSearchPlan:
    return TelegramSearchPlan(
        message_id="telegram-link-1",
        message_url="https://t.me/manual/telegram-link-1",
        message_text="Attack on oil terminal in Iran",
        event_type="attack",
        target="energy infrastructure",
        country="Iran",
        domain="INFRASTRUCTURE",
        search="attack energy infrastructure Iran",
        signal_score=3,
        published_at="2026-07-25T12:00:00+00:00",
    )


def test_pipeline_persists_message_to_search_link(tmp_path):
    database_path = tmp_path / "pricegauger.db"
    plan = sample_plan()

    result = ingest_telegram_plan_to_gdelt(
        plan,
        FakeGdeltProvider(),
        provider_name="GDELT DOC",
        date_start="2026-06-25",
        date_end="2026-07-25",
        limit=5,
        database_path=database_path,
        retrieved_at=datetime(2026, 7, 25, 13, 0, tzinfo=timezone.utc),
    )

    links = load_telegram_gdelt_search_links(
        plan.message_id,
        database_path=database_path,
    )
    assert len(links) == 1
    assert links[0].message_id == plan.message_id
    assert links[0].message_url == plan.message_url
    assert links[0].message_text == plan.message_text
    assert links[0].published_at == plan.published_at
    assert links[0].search_id == result.search_id
    assert load_gdelt_candidates(result.search_id, database_path=database_path)


def test_message_search_link_is_idempotent(tmp_path):
    database_path = tmp_path / "pricegauger.db"
    plan = sample_plan()

    for _ in range(2):
        ingest_telegram_plan_to_gdelt(
            plan,
            FakeGdeltProvider(),
            provider_name="GDELT DOC",
            date_start="2026-06-25",
            date_end="2026-07-25",
            limit=5,
            database_path=database_path,
        )

    links = load_telegram_gdelt_search_links(
        plan.message_id,
        database_path=database_path,
    )
    assert len(links) == 1
