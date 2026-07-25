from datetime import datetime, timezone

import pytest

from event_models import MarketEvent
from gdelt_ingestion import GdeltSearchRequest, ingest_gdelt_candidates
from gdelt_types import GdeltPage


class FakeGdeltProvider:
    def __init__(self, page: GdeltPage) -> None:
        self.page = page
        self.calls: list[dict] = []

    def list_events(self, **kwargs):
        self.calls.append(kwargs)
        return self.page


def sample_event() -> MarketEvent:
    return MarketEvent(
        event_id="gdelt-doc:test-1",
        source="gdelt_doc_v2",
        event_date="2026-07-24",
        title="Oil terminal disrupted",
        summary="Oil terminal disrupted",
        category="news_coverage",
        subcategory="article",
        domain="example.com",
        country="Iran",
        location="",
        actors=[],
        confidence=None,
        market_sensitivity=None,
        significance=None,
        url="https://example.com/story",
        raw={"url": "https://example.com/story", "seendate": "20260724120000"},
        published_at="2026-07-24T12:00:00+00:00",
        timestamp_source="gdelt:seendate",
        timestamp_confidence=0.85,
    )


def test_ingestion_preserves_raw_event_and_provider_provenance():
    provider = FakeGdeltProvider(GdeltPage(events=[sample_event()], next_cursor=None))
    request = GdeltSearchRequest(
        date_start="2024-01-01",
        date_end="2026-07-24",
        search='"oil terminal" disruption',
        country="Iran",
        limit=25,
    )

    records, warning = ingest_gdelt_candidates(
        provider,
        request,
        provider_name="GDELT DOC",
        retrieved_at=datetime(2026, 7, 25, 8, 0, tzinfo=timezone.utc),
    )

    assert warning is None
    assert len(records) == 1
    record = records[0]
    assert record.provider == "GDELT DOC"
    assert record.query == '"oil terminal" disruption'
    assert record.event_id == "gdelt-doc:test-1"
    assert record.published_at == "2026-07-24T12:00:00+00:00"
    assert record.raw["seendate"] == "20260724120000"
    assert record.schema_version == "gdelt-candidate-v1"
    assert provider.calls == [
        {
            "date_start": "2024-01-01",
            "date_end": "2026-07-24",
            "search": '"oil terminal" disruption',
            "country": "Iran",
            "domain": "",
            "confidence_profile": "precise",
            "sort": "significance",
            "limit": 25,
        }
    ]


def test_provider_warning_is_returned_without_becoming_analysis():
    provider = FakeGdeltProvider(
        GdeltPage(events=[], next_cursor=None, warning="No candidates")
    )
    records, warning = ingest_gdelt_candidates(
        provider,
        GdeltSearchRequest(
            date_start="2026-01-01",
            date_end="2026-07-24",
            search="shipping disruption",
        ),
        provider_name="GDELT Cloud",
    )

    assert records == []
    assert warning == "No candidates"


@pytest.mark.parametrize("search", ["", "   "])
def test_empty_search_is_rejected(search: str):
    with pytest.raises(ValueError, match="search must not be empty"):
        GdeltSearchRequest(
            date_start="2026-01-01",
            date_end="2026-07-24",
            search=search,
        )
