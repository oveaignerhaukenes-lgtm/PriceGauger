from datetime import datetime, timezone

import pytest

from event_models import MarketEvent
from gdelt_candidate_store import load_gdelt_candidates, save_gdelt_candidates
from gdelt_ingestion import GdeltSearchRequest, ingest_gdelt_candidates
from gdelt_types import GdeltPage


class FakeGdeltProvider:
    def list_events(self, **kwargs):
        del kwargs
        return GdeltPage(
            events=[
                MarketEvent(
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
                    raw={"url": "https://example.com/story", "tone": -3.2},
                    published_at="2026-07-24T12:00:00+00:00",
                    timestamp_source="gdelt:seendate",
                    timestamp_confidence=0.85,
                )
            ],
            next_cursor=None,
        )


def test_candidates_round_trip_through_sqlite(tmp_path):
    database_path = tmp_path / "pricegauger.db"
    request = GdeltSearchRequest(
        date_start="2024-01-01",
        date_end="2026-07-24",
        search='"oil terminal" disruption',
        country="Iran",
        limit=25,
    )
    records, warning = ingest_gdelt_candidates(
        FakeGdeltProvider(),
        request,
        provider_name="GDELT DOC",
        retrieved_at=datetime(2026, 7, 25, 8, 0, tzinfo=timezone.utc),
    )

    assert warning is None
    assert save_gdelt_candidates(request, records, database_path=database_path) == 1

    loaded = load_gdelt_candidates(request.search_id, database_path=database_path)
    assert loaded == records
    assert loaded[0].raw["tone"] == -3.2


def test_repeated_save_is_idempotent_and_updates_data(tmp_path):
    database_path = tmp_path / "pricegauger.db"
    request = GdeltSearchRequest(
        date_start="2024-01-01",
        date_end="2026-07-24",
        search="shipping disruption",
    )
    records, _ = ingest_gdelt_candidates(
        FakeGdeltProvider(),
        request,
        provider_name="GDELT DOC",
        retrieved_at=datetime(2026, 7, 25, 8, 0, tzinfo=timezone.utc),
    )

    save_gdelt_candidates(request, records, database_path=database_path)
    save_gdelt_candidates(request, records, database_path=database_path)

    loaded = load_gdelt_candidates(request.search_id, database_path=database_path)
    assert len(loaded) == 1


def test_candidate_from_another_search_is_rejected(tmp_path):
    first = GdeltSearchRequest(
        date_start="2024-01-01",
        date_end="2026-07-24",
        search="shipping disruption",
    )
    second = GdeltSearchRequest(
        date_start="2024-01-01",
        date_end="2026-07-24",
        search="pipeline outage",
    )
    records, _ = ingest_gdelt_candidates(
        FakeGdeltProvider(),
        first,
        provider_name="GDELT DOC",
    )

    with pytest.raises(ValueError, match="candidate search_id"):
        save_gdelt_candidates(second, records, database_path=tmp_path / "pricegauger.db")
