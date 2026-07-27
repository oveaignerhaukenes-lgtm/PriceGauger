from datetime import datetime, timezone

import pytest

import gdelt_runtime
from event_models import MarketEvent
from gdelt_types import GdeltPage
from telegram_query_builder import TelegramSearchPlan


class FakeConfiguredClient:
    def __init__(self, api_key: str, timeout: int = 30) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self.calls: list[dict] = []

    def list_events(self, **kwargs):
        self.calls.append(kwargs)
        return GdeltPage(
            events=[
                MarketEvent(
                    event_id="gdelt-doc:configured-1",
                    source="gdelt_doc_v2",
                    event_date="2026-07-24",
                    title="Pipeline disrupted",
                    summary="Pipeline disrupted",
                    category="news_coverage",
                    subcategory="article",
                    domain="example.com",
                    country="Iran",
                    location="",
                    actors=[],
                    confidence=None,
                    market_sensitivity=None,
                    significance=None,
                    url="https://example.com/configured",
                    raw={"source": "configured-test"},
                    published_at="2026-07-24T12:00:00+00:00",
                    timestamp_source="gdelt:seendate",
                    timestamp_confidence=0.85,
                )
            ],
            next_cursor=None,
        )


class FakeBigQueryClient:
    def __init__(self, project: str, maximum_bytes_billed: int) -> None:
        self.project = project
        self.maximum_bytes_billed = maximum_bytes_billed


def sample_plan() -> TelegramSearchPlan:
    return TelegramSearchPlan(
        message_id="123",
        message_url="https://t.me/test/123",
        message_text="Iran pipeline disrupted",
        event_type="blockade",
        target="energy infrastructure",
        country="Iran",
        domain="INFRASTRUCTURE",
        search="blockade energy infrastructure Iran",
        signal_score=3,
        published_at="2026-07-25T08:00:00+00:00",
    )


def test_direct_configuration_builds_doc_provider(monkeypatch):
    monkeypatch.setattr(gdelt_runtime, "GdeltClient", FakeConfiguredClient)

    configured = gdelt_runtime.build_configured_gdelt_provider(
        provider_loader=lambda: "direct",
        api_key_loader=lambda: "__DIRECT__",
        timeout=12,
    )

    assert configured.provider_mode == "direct"
    assert configured.provider_name == "GDELT DOC"
    assert configured.client.api_key == "__DIRECT__"
    assert configured.client.timeout == 12


def test_bigquery_configuration_builds_cost_bounded_provider(monkeypatch):
    monkeypatch.setattr(gdelt_runtime, "BigQueryGdeltClient", FakeBigQueryClient)

    configured = gdelt_runtime.build_configured_gdelt_provider(
        provider_loader=lambda: "bigquery",
        bigquery_project_loader=lambda: "pricegauger",
        bigquery_max_bytes_loader=lambda: 12345,
    )

    assert configured.provider_mode == "bigquery"
    assert configured.provider_name == "GDELT BigQuery"
    assert configured.client.project == "pricegauger"
    assert configured.client.maximum_bytes_billed == 12345


def test_cloud_configuration_requires_token():
    with pytest.raises(ValueError, match="GDELT_CLOUD_API_KEY"):
        gdelt_runtime.build_configured_gdelt_provider(
            provider_loader=lambda: "cloud",
            api_key_loader=lambda: "",
        )


def test_configured_pipeline_persists_candidates(monkeypatch, tmp_path):
    monkeypatch.setattr(gdelt_runtime, "GdeltClient", FakeConfiguredClient)

    result = gdelt_runtime.ingest_telegram_plan_with_configured_gdelt(
        sample_plan(),
        date_start="2024-01-01",
        date_end="2026-07-25",
        database_path=tmp_path / "pricegauger.db",
        retrieved_at=datetime(2026, 7, 25, 9, 0, tzinfo=timezone.utc),
        provider_loader=lambda: "direct",
        api_key_loader=lambda: "__DIRECT__",
    )

    assert result.message_id == "123"
    assert result.candidate_count == 1
    assert result.saved_count == 1
    assert result.candidates[0].provider == "GDELT DOC"
    assert result.candidates[0].raw["source"] == "configured-test"
