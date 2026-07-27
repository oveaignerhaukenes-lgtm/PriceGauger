from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from gdelt_candidate_store import load_gdelt_candidates
from gdelt_ingestion import GdeltCandidateRecord
from storage import DB_PATH
from telegram_gdelt_link_store import (
    TelegramGdeltSearchLink,
    load_telegram_gdelt_search_links,
)


@dataclass(frozen=True, slots=True)
class TelegramGdeltHistory:
    message_id: str
    message_url: str
    message_text: str
    published_at: str
    searches: tuple[TelegramGdeltSearchLink, ...]
    candidates: tuple[GdeltCandidateRecord, ...]


def load_telegram_gdelt_history(
    message_id: str,
    *,
    search_id: str | None = None,
    database_path: Path | str = DB_PATH,
) -> TelegramGdeltHistory | None:
    """Load stored GDELT candidates for one Telegram message without API calls.

    When ``search_id`` is supplied, only that exact persisted search is returned.
    Omitting it preserves the broader historical view across every stored search for
    the Telegram message.
    """
    links = load_telegram_gdelt_search_links(
        message_id,
        database_path=database_path,
    )
    if search_id is not None:
        links = [link for link in links if link.search_id == search_id]
    if not links:
        return None

    candidates: list[GdeltCandidateRecord] = []
    seen: set[tuple[str, str]] = set()
    for link in links:
        for candidate in load_gdelt_candidates(
            link.search_id,
            database_path=database_path,
        ):
            identity = (candidate.event_id, candidate.provider)
            if identity in seen:
                continue
            seen.add(identity)
            candidates.append(candidate)

    candidates.sort(
        key=lambda candidate: (
            candidate.published_at or "",
            candidate.event_id,
        ),
        reverse=True,
    )
    latest = links[0]
    return TelegramGdeltHistory(
        message_id=latest.message_id,
        message_url=latest.message_url,
        message_text=latest.message_text,
        published_at=latest.published_at,
        searches=tuple(links),
        candidates=tuple(candidates),
    )
