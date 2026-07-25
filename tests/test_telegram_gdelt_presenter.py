from telegram_gdelt_history import TelegramGdeltHistory
from telegram_gdelt_ingestion import GdeltCandidateRecord
from telegram_gdelt_link_store import TelegramGdeltSearchLink
from telegram_gdelt_pipeline import TelegramGdeltIngestionResult
from telegram_gdelt_presenter import (
    latest_result_candidate_rows,
    latest_result_summary,
)
from telegram_gdelt_service import LatestTelegramGdeltResult
from telegram_query_builder import TelegramSearchPlan


def sample_result() -> LatestTelegramGdeltResult:
    plan = TelegramSearchPlan(
        message_id="presenter-1",
        message_url="https://t.me/manual/presenter-1",
        message_text="Attack on oil terminal in Iran",
        event_type="attack",
        target="energy infrastructure",
        country="Iran",
        domain="INFRASTRUCTURE",
        search="attack energy infrastructure Iran",
        signal_score=3,
        published_at="2026-07-25T12:00:00+00:00",
    )
    candidate = GdeltCandidateRecord(
        search_id="gdelt-search:presenter",
        event_id="gdelt-doc:presenter",
        provider="GDELT DOC",
        query=plan.search,
        title="Historical terminal disruption",
        summary="Historical terminal disruption",
        published_at="2026-07-20T12:00:00+00:00",
        event_date="2026-07-20",
        country="Turkey",
        domain="example.com",
        url="https://example.com/article",
        retrieved_at="2026-07-25T13:00:00+00:00",
        raw={"seendate": "20260720T120000Z"},
        schema_version="gdelt-candidate-v1",
    )
    link = TelegramGdeltSearchLink(
        message_id=plan.message_id,
        message_url=plan.message_url,
        message_text=plan.message_text,
        published_at=plan.published_at,
        search_id=candidate.search_id,
        created_at="2026-07-25 13:00:00",
    )
    ingestion = TelegramGdeltIngestionResult(
        message_id=plan.message_id,
        search_id=candidate.search_id,
        candidate_count=1,
        saved_count=1,
        warning=None,
        candidates=(candidate,),
    )
    history = TelegramGdeltHistory(
        message_id=plan.message_id,
        message_url=plan.message_url,
        message_text=plan.message_text,
        published_at=plan.published_at,
        searches=(link,),
        candidates=(candidate,),
    )
    return LatestTelegramGdeltResult(plan=plan, ingestion=ingestion, history=history)


def test_latest_result_summary_exposes_core_flow_counts():
    summary = latest_result_summary(sample_result())

    assert summary["message_id"] == "presenter-1"
    assert summary["event_type"] == "attack"
    assert summary["search_count"] == 1
    assert summary["candidate_count"] == 1
    assert summary["warning"] is None


def test_latest_result_candidate_rows_preserve_stored_order_and_provenance():
    rows = latest_result_candidate_rows(sample_result())

    assert rows == [
        {
            "published_at": "2026-07-20T12:00:00+00:00",
            "title": "Historical terminal disruption",
            "domain": "example.com",
            "source_country": "Turkey",
            "provider": "GDELT DOC",
            "url": "https://example.com/article",
        }
    ]
