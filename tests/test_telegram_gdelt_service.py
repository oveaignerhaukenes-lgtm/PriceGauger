from datetime import date

from event_models import MarketEvent
from gdelt_types import GdeltPage
from telegram_gdelt_pipeline import ingest_telegram_plan_to_gdelt
from telegram_gdelt_service import process_latest_telegram_with_gdelt
from telegram_query_builder import TelegramSearchPlan


class FakeProvider:
    def list_events(self, **kwargs):
        return GdeltPage(
            events=[
                MarketEvent(
                    event_id="gdelt-doc:service-test",
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
                    url="https://example.com/service-test",
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
        message_id="service-message-1",
        message_url="https://t.me/manual/service-message-1",
        message_text="Attack on oil terminal in Iran",
        event_type="attack",
        target="energy infrastructure",
        country="Iran",
        domain="INFRASTRUCTURE",
        search="attack energy infrastructure Iran",
        signal_score=3,
        published_at="2026-07-25T12:00:00+00:00",
    )


def test_service_processes_latest_plan_and_reads_persisted_history(tmp_path):
    calls = {}
    plan = sample_plan()

    def plan_loader(channel, *, minimum_signal, timeout):
        calls["loader"] = (channel, minimum_signal, timeout)
        return plan

    def ingestion_runner(plan_arg, **kwargs):
        calls["ingestion"] = kwargs
        return ingest_telegram_plan_to_gdelt(
            plan_arg,
            FakeProvider(),
            provider_name="GDELT DOC",
            date_start=kwargs["date_start"],
            date_end=kwargs["date_end"],
            limit=kwargs["limit"],
            database_path=kwargs["database_path"],
        )

    result = process_latest_telegram_with_gdelt(
        channel="Middle_East_Spectator",
        lookback_days=30,
        limit=5,
        database_path=tmp_path / "pricegauger.db",
        timeout=12,
        today=date(2026, 7, 25),
        plan_loader=plan_loader,
        ingestion_runner=ingestion_runner,
    )

    assert result is not None
    assert result.plan == plan
    assert result.ingestion.candidate_count == 1
    assert result.history.message_id == plan.message_id
    assert len(result.history.candidates) == 1
    assert calls["loader"] == ("Middle_East_Spectator", 2, 12)
    assert calls["ingestion"]["date_start"] == "2026-06-25"
    assert calls["ingestion"]["date_end"] == "2026-07-25"
    assert calls["ingestion"]["limit"] == 5
    assert calls["ingestion"]["timeout"] == 12


def test_service_returns_none_when_no_relevant_telegram_plan(tmp_path):
    def plan_loader(channel, *, minimum_signal, timeout):
        return None

    def ingestion_runner(*args, **kwargs):
        raise AssertionError("ingestion must not run without a Telegram plan")

    result = process_latest_telegram_with_gdelt(
        database_path=tmp_path / "pricegauger.db",
        plan_loader=plan_loader,
        ingestion_runner=ingestion_runner,
    )

    assert result is None
