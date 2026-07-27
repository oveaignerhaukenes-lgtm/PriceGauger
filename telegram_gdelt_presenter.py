from __future__ import annotations

from typing import Any

from telegram_gdelt_service import LatestTelegramGdeltResult


def latest_result_summary(result: LatestTelegramGdeltResult) -> dict[str, Any]:
    """Return a small UI-safe summary without starting new data work."""
    return {
        "message_id": result.plan.message_id,
        "message_url": result.plan.message_url,
        "message_text": result.plan.message_text,
        "published_at": result.plan.published_at,
        "event_type": result.plan.event_type,
        "target": result.plan.target,
        "country": result.plan.country,
        "search": result.plan.search,
        "search_id": result.ingestion.search_id,
        "search_count": len(result.history.searches),
        "candidate_count": len(result.ingestion.candidates),
        "warning": result.ingestion.warning,
    }


def latest_result_candidate_rows(result: LatestTelegramGdeltResult) -> list[dict[str, Any]]:
    """Return candidates from the current provider run, with no ranking or inference."""
    return [
        {
            "published_at": candidate.published_at or "",
            "title": candidate.title,
            "domain": candidate.domain,
            "source_country": candidate.country,
            "provider": candidate.provider,
            "url": candidate.url,
        }
        for candidate in result.ingestion.candidates
    ]
