from gdelt_ingestion import GdeltCandidateRecord
from telegram_gdelt_history import TelegramGdeltHistory
from telegram_gdelt_link_store import TelegramGdeltSearchLink
from telegram_gdelt_pipeline import TelegramGdeltIngestionResult
from telegram_gdelt_presenter import (
    latest_result_candidate_rows,
    latest_result_summary,
)
from telegram_gdelt_service import LatestTelegramGdeltResult
from telegram_query_builder import TelegramSearchPlan


def _candidate(*, event_id: str, provider: str, title: str, url: str) -> GdeltCandidateRecord:
    return GdeltCandidateRecord(
        search_id="gdelt-search:presenter",
        event_id=event_id,
        provider=provider,
        query="attack energy infrastructure Iran",
        title=title,
        summary=title,
        published_at="2026-07-20T12:00:00+00:00",
        event_date="2026-07-20",
        country="Iran",
        domain="example.com",
        url=url,
        retrieved_at="2026-07-25T13:00:00+00:00",
        raw={"source": provider},
        schema_version="gdelt-candidate-v1",
    )


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
    current_candidate = _candidate(
        event_id="gdelt-bq:presenter",
        provider="GDELT BigQuery",
        title="IRAN ↔ IRAQ · CAMEO 190",
        url="https://example.com/bigquery",
    )
    old_candidate = _candidate(
        event_id="gdelt-doc:presenter",
        provider="GDELT DOC",
        title="Old DOC article",
        url="https://example.com/doc",
    )
    link = TelegramGdeltSearchLink(
        message_id=plan.message_id,
        message_url=plan.message_url,
        message_text=plan.message_text,
        published_at=plan.published_at,
        search_id=current_candidate.search_id,
        created_at="2026-07-25 13:00:00",
    )
    ingestion = TelegramGdeltIngestionResult(
        message_id=plan.message_id,
        search_id=current_candidate.search_id,
        candidate_count=1,
        saved_count=1,
        warning=None,
        candidates=(current_candidate,),
    )
    history = TelegramGdeltHistory(
        message_id=plan.message_id,
        message_url=plan.message_url,
        message_text=plan.message_text,
        published_at=plan.published_at,
        searches=(link,),
        candidates=(old_candidate, current_candidate),
    )
    return LatestTelegramGdeltResult(plan=plan, ingestion=ingestion, history=history)


def test_latest_result_summary_exposes_current_run_counts():
    summary = latest_result_summary(sample_result())

    assert summary["message_id"] == "presenter-1"
    assert summary["event_type"] == "attack"
    assert summary["search_count"] == 1
    assert summary["candidate_count"] == 1
    assert summary["warning"] is None


def test_latest_result_candidate_rows_use_current_ingestion_not_mixed_history():
    rows = latest_result_candidate_rows(sample_result())

    assert rows == [
        {
            "published_at": "2026-07-20T12:00:00+00:00",
            "title": "IRAN ↔ IRAQ · CAMEO 190",
            "domain": "example.com",
            "source_country": "Iran",
            "provider": "GDELT BigQuery",
            "url": "https://example.com/bigquery",
        }
    ]
