from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from gdelt_candidate_store import save_gdelt_candidates
from gdelt_ingestion import (
    GdeltCandidateRecord,
    GdeltProvider,
    GdeltSearchRequest,
    ingest_gdelt_candidates,
)
from storage import DB_PATH
from telegram_query_builder import TelegramSearchPlan


@dataclass(frozen=True, slots=True)
class TelegramGdeltIngestionResult:
    message_id: str
    search_id: str
    candidate_count: int
    saved_count: int
    warning: str | None
    candidates: tuple[GdeltCandidateRecord, ...]


def gdelt_request_from_telegram_plan(
    plan: TelegramSearchPlan,
    *,
    date_start: str,
    date_end: str,
    limit: int = 50,
    confidence_profile: str = "precise",
    sort: str = "significance",
) -> GdeltSearchRequest:
    """Translate an existing Telegram plan into the GDELT data contract.

    Date bounds stay explicit so this boundary does not silently choose a
    historical window or embed analogue-ranking policy.
    """
    if not plan.search.strip():
        raise ValueError("Telegram search plan has no search query")

    return GdeltSearchRequest(
        date_start=date_start,
        date_end=date_end,
        search=plan.search,
        country=plan.country,
        limit=limit,
        confidence_profile=confidence_profile,
        sort=sort,
    )


def ingest_telegram_plan_to_gdelt(
    plan: TelegramSearchPlan,
    provider: GdeltProvider,
    *,
    provider_name: str,
    date_start: str,
    date_end: str,
    limit: int = 50,
    database_path: Path | str = DB_PATH,
    retrieved_at: datetime | None = None,
) -> TelegramGdeltIngestionResult:
    """Fetch, normalize and persist GDELT candidates for one Telegram plan."""
    request = gdelt_request_from_telegram_plan(
        plan,
        date_start=date_start,
        date_end=date_end,
        limit=limit,
    )
    candidates, warning = ingest_gdelt_candidates(
        provider,
        request,
        provider_name=provider_name,
        retrieved_at=retrieved_at,
    )
    saved_count = save_gdelt_candidates(
        request,
        candidates,
        database_path=database_path,
    )
    return TelegramGdeltIngestionResult(
        message_id=plan.message_id,
        search_id=request.search_id,
        candidate_count=len(candidates),
        saved_count=saved_count,
        warning=warning,
        candidates=tuple(candidates),
    )
