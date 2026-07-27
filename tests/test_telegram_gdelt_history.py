from datetime import datetime, timezone

from event_models import MarketEvent
from gdelt_types import GdeltPage
from telegram_gdelt_history import load_telegram_gdelt_history
from telegram_gdelt_pipeline import ingest_telegram_plan_to_gdelt
from telegram_query_builder import TelegramSearchPlan


class FakeGdeltProvider:
    def __init__(
        self,
        *,
        event_id: str = "gdelt-doc:history-test",
        title: str = "Oil terminal disrupted after attack",
        url: str = "https://example.com/history-test",
        source: str = "gdelt_doc_v2",
    ) -> None:
        self.event_id = event_id
        self.title = title
        self.url = url
        self.source = source

    def list_events(self, **kwargs):
        return GdeltPage(
            events=[
                MarketEvent(
                    event_id=self.event_id,
                    source=self.source,
                    event_date="2026-07-20",
                    title=self.title,
                    summary=self.title,
                    category="news_coverage",
                    subcategory="article",
                    domain="example.com",
                    country="Iran",
                    location="",
                    actors=[],
                    confidence=None,
                    market_sensitivity=None,
                    significance=None,
                    url=self.url,
                    raw={"seendate": "20260720T120000Z"},
                    published_at="2026-07-20T12:00:00+00:00",
                    timestamp_source="gdelt:seendate",
                    timestamp_confidence=0.85,
                )
            ],
            next_cursor=None,
        )


def sample_plan(*, search: str = "attack energy infrastructure Iran") -> TelegramSearchPlan:
    return TelegramSearchPlan(
        message_id="telegram-history-1",
        message_url="https://t.me/manual/telegram-history-1",
        message_text="Attack on oil terminal in Iran",
        event_type="attack",
        target="energy infrastructure",
        country="Iran",
        domain="INFRASTRUCTURE",
        search=search,
        signal_score=3,
        published_at="2026-07-25T12:00:00+00:00",
    )


def test_load_history_returns_message_searches_and_candidates(tmp_path):
    database_path = tmp_path / "pricegauger.db"
    plan = sample_plan()
    ingest_telegram_plan_to_gdelt(
        plan,
        FakeGdeltProvider(),
        provider_name="GDELT DOC",
        date_start="2026-06-25",
        date_end="2026-07-25",
        limit=5,
        database_path=database_path,
        retrieved_at=datetime(2026, 7, 25, 13, 0, tzinfo=timezone.utc),
    )

    history = load_telegram_gdelt_history(
        plan.message_id,
        database_path=database_path,
    )

    assert history is not None
    assert history.message_id == plan.message_id
    assert history.message_url == plan.message_url
    assert history.message_text == plan.message_text
    assert history.published_at == plan.published_at
    assert len(history.searches) == 1
    assert len(history.candidates) == 1
    assert history.candidates[0].title == "Oil terminal disrupted after attack"


def test_load_history_can_return_only_one_exact_search(tmp_path):
    database_path = tmp_path / "pricegauger.db"
    old_plan = sample_plan(search="attack Iran")
    current_plan = sample_plan(search="drone attack Erbil Iraq Iran")

    old_result = ingest_telegram_plan_to_gdelt(
        old_plan,
        FakeGdeltProvider(
            event_id="gdelt-doc:old",
            title="Old DOC candidate",
            url="https://example.com/old-doc",
        ),
        provider_name="GDELT DOC",
        date_start="2026-06-25",
        date_end="2026-07-25",
        limit=5,
        database_path=database_path,
    )
    current_result = ingest_telegram_plan_to_gdelt(
        current_plan,
        FakeGdeltProvider(
            event_id="gdelt-bq:current",
            title="Current BigQuery candidate",
            url="https://example.com/current-bigquery",
            source="gdelt_bigquery_v2",
        ),
        provider_name="GDELT BigQuery",
        date_start="2026-06-25",
        date_end="2026-07-25",
        limit=5,
        database_path=database_path,
    )

    history = load_telegram_gdelt_history(
        current_plan.message_id,
        search_id=current_result.search_id,
        database_path=database_path,
    )

    assert old_result.search_id != current_result.search_id
    assert history is not None
    assert [link.search_id for link in history.searches] == [current_result.search_id]
    assert [candidate.provider for candidate in history.candidates] == ["GDELT BigQuery"]
    assert [candidate.title for candidate in history.candidates] == ["Current BigQuery candidate"]


def test_load_history_returns_none_for_unknown_message(tmp_path):
    history = load_telegram_gdelt_history(
        "missing-message",
        database_path=tmp_path / "pricegauger.db",
    )

    assert history is None
