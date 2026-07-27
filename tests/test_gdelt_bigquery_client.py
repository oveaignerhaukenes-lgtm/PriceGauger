from __future__ import annotations

from dataclasses import dataclass

import pytest

from gdelt_bigquery_client import BigQueryGdeltClient
from gdelt_types import GdeltError


@dataclass
class FakeQueryJobConfig:
    query_parameters: list | None = None
    dry_run: bool = False
    use_query_cache: bool = True
    maximum_bytes_billed: int | None = None


@dataclass
class FakeScalarQueryParameter:
    name: str
    type_: str
    value: object


class FakeBigQueryModule:
    QueryJobConfig = FakeQueryJobConfig
    ScalarQueryParameter = FakeScalarQueryParameter


class FakeDryJob:
    def __init__(self, total_bytes_processed: int) -> None:
        self.total_bytes_processed = total_bytes_processed


class FakeRunJob:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def result(self):
        return self._rows


class FakeClient:
    def __init__(self, rows: list[dict], estimated_bytes: int = 1024) -> None:
        self.rows = rows
        self.estimated_bytes = estimated_bytes
        self.calls: list[tuple[str, FakeQueryJobConfig, str]] = []

    def query(self, query, *, job_config, location):
        self.calls.append((query, job_config, location))
        if job_config.dry_run:
            return FakeDryJob(self.estimated_bytes)
        return FakeRunJob(self.rows)


def sample_row(*, event_id: int = 1, url: str = "https://example.com/story") -> dict:
    return {
        "GLOBALEVENTID": event_id,
        "SQLDATE": 20260727,
        "Actor1Name": "IRAN",
        "Actor2Name": "UNITED STATES",
        "EventCode": "046",
        "EventRootCode": "04",
        "GoldsteinScale": 7.0,
        "NumMentions": 28,
        "ActionGeo_CountryCode": "US",
        "ActionGeo_FullName": "Washington, United States",
        "SOURCEURL": url,
        "DATEADDED": 20260727123000,
    }


def test_bigquery_provider_dry_runs_executes_and_normalizes():
    fake = FakeClient([sample_row()])
    client = BigQueryGdeltClient(
        project="pricegauger",
        maximum_bytes_billed=5 * 1024**3,
        client=fake,
        bigquery_module=FakeBigQueryModule,
    )

    page = client.list_events(
        date_start="2026-07-24",
        date_end="2026-07-27",
        search="Iran United States talks",
        country="Iran",
        limit=20,
    )

    assert len(fake.calls) == 2
    assert fake.calls[0][1].dry_run is True
    assert fake.calls[1][1].maximum_bytes_billed == 5 * 1024**3
    assert page.warning is None
    assert len(page.events) == 1
    event = page.events[0]
    assert event.source == "gdelt_bigquery_v2"
    assert event.event_date == "2026-07-27"
    assert event.actors == ["IRAN", "UNITED STATES"]
    assert event.url == "https://example.com/story"
    assert event.published_at == "2026-07-27T12:30:00+00:00"


def test_bigquery_provider_deduplicates_source_urls():
    fake = FakeClient(
        [
            sample_row(event_id=1),
            sample_row(event_id=2),
        ]
    )
    client = BigQueryGdeltClient(
        client=fake,
        bigquery_module=FakeBigQueryModule,
    )

    page = client.list_events(
        date_start="2026-07-24",
        date_end="2026-07-27",
        search="Iran",
        country="Iran",
    )

    assert len(page.events) == 1


def test_bigquery_provider_rejects_query_above_byte_ceiling():
    fake = FakeClient([sample_row()], estimated_bytes=101)
    client = BigQueryGdeltClient(
        maximum_bytes_billed=100,
        client=fake,
        bigquery_module=FakeBigQueryModule,
    )

    with pytest.raises(GdeltError, match="kostnadsgrensen"):
        client.list_events(
            date_start="2026-07-24",
            date_end="2026-07-27",
            search="Iran",
            country="Iran",
        )

    assert len(fake.calls) == 1
