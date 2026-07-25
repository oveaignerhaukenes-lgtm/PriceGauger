from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path("data/pricegauger.db")


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS analysis_events (
            event_id TEXT PRIMARY KEY,
            published_at TEXT,
            source TEXT NOT NULL,
            source_channel TEXT,
            raw_text TEXT NOT NULL,
            source_url TEXT,
            summary TEXT,
            event_type TEXT,
            target TEXT,
            country TEXT,
            domain TEXT,
            search_query TEXT,
            affected_assets_json TEXT NOT NULL DEFAULT '[]',
            semantic_confidence REAL,
            canonical_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.commit()
    return connection


def save_analysis_event(
    *,
    event_id: str,
    published_at: str,
    source: str,
    source_channel: str = "",
    raw_text: str,
    source_url: str = "",
    summary: str = "",
    event_type: str = "",
    target: str = "",
    country: str = "",
    domain: str = "",
    search_query: str = "",
    affected_assets: list[str] | tuple[str, ...] = (),
    semantic_confidence: float | None = None,
    canonical: dict[str, Any] | None = None,
) -> None:
    created_at = datetime.now(timezone.utc).isoformat()
    payload = canonical or {}
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO analysis_events (
                event_id, published_at, source, source_channel, raw_text,
                source_url, summary, event_type, target, country, domain,
                search_query, affected_assets_json, semantic_confidence,
                canonical_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_id) DO UPDATE SET
                published_at=excluded.published_at,
                source=excluded.source,
                source_channel=excluded.source_channel,
                raw_text=excluded.raw_text,
                source_url=excluded.source_url,
                summary=excluded.summary,
                event_type=excluded.event_type,
                target=excluded.target,
                country=excluded.country,
                domain=excluded.domain,
                search_query=excluded.search_query,
                affected_assets_json=excluded.affected_assets_json,
                semantic_confidence=excluded.semantic_confidence,
                canonical_json=excluded.canonical_json
            """,
            (
                event_id,
                published_at,
                source,
                source_channel,
                raw_text,
                source_url,
                summary,
                event_type,
                target,
                country,
                domain,
                search_query,
                json.dumps(list(affected_assets), ensure_ascii=False),
                semantic_confidence,
                json.dumps(payload, ensure_ascii=False),
                created_at,
            ),
        )
        connection.commit()


def list_analysis_events(limit: int = 100) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT * FROM analysis_events
            ORDER BY COALESCE(NULLIF(published_at, ''), created_at) DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    results: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["affected_assets"] = json.loads(item.pop("affected_assets_json") or "[]")
        item["canonical"] = json.loads(item.pop("canonical_json") or "{}")
        results.append(item)
    return results


def latest_analysis_event() -> dict[str, Any] | None:
    events = list_analysis_events(limit=1)
    return events[0] if events else None
