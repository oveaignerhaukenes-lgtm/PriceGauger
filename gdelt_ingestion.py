from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from gdelt_types import GdeltPage


@dataclass(frozen=True, slots=True)
class GdeltSearchRequest:
    date_start: str
    date_end: str
    search: str
    country: str = ""
    domain: str = ""
    limit: int = 50
    confidence_profile: str = "precise"
    sort: str = "significance"

    def __post_init__(self) -> None:
        if not self.date_start or not self.date_end:
            raise ValueError("date_start and date_end are required")
        if not self.search.strip():
            raise ValueError("search must not be empty")
        if self.limit < 1 or self.limit > 100:
            raise ValueError("limit must be between 1 and 100")


@dataclass(frozen=True, slots=True)
class GdeltCandidateRecord:
    event_id: str
    provider: str
    query: str
    title: str
    summary: str
    published_at: str | None
    event_date: str
    country: str
    domain: str
    url: str
    retrieved_at: str
    raw: dict[str, Any]
    schema_version: str = "gdelt-candidate-v1"

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


class GdeltProvider(Protocol):
    def list_events(self, **kwargs: Any) -> GdeltPage: ...


def ingest_gdelt_candidates(
    provider: GdeltProvider,
    request: GdeltSearchRequest,
    *,
    provider_name: str,
    retrieved_at: datetime | None = None,
) -> tuple[list[GdeltCandidateRecord], str | None]:
    """Fetch and normalize GDELT candidates without ranking or prediction.

    This is deliberately a data-boundary function. It preserves the provider's
    raw metadata and does not decide whether an event is a good historical analogue.
    """

    page = provider.list_events(
        date_start=request.date_start,
        date_end=request.date_end,
        search=request.search,
        country=request.country,
        domain=request.domain,
        confidence_profile=request.confidence_profile,
        sort=request.sort,
        limit=request.limit,
    )
    timestamp = (retrieved_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    records = [
        GdeltCandidateRecord(
            event_id=event.event_id,
            provider=provider_name,
            query=request.search,
            title=event.title,
            summary=event.summary,
            published_at=event.published_at,
            event_date=event.event_date,
            country=event.country,
            domain=event.domain,
            url=event.url,
            retrieved_at=timestamp,
            raw=dict(event.raw),
        )
        for event in page.events
    ]
    return records, page.warning
