from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

from gdelt_ingestion import GdeltCandidateRecord, GdeltSearchRequest
from storage import DB_PATH


def _connect(database_path: Path | str = DB_PATH) -> sqlite3.Connection:
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS gdelt_searches (
            search_id TEXT PRIMARY KEY,
            date_start TEXT NOT NULL,
            date_end TEXT NOT NULL,
            query TEXT NOT NULL,
            country TEXT NOT NULL,
            domain TEXT NOT NULL,
            result_limit INTEGER NOT NULL,
            confidence_profile TEXT NOT NULL,
            sort TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS gdelt_candidates (
            search_id TEXT NOT NULL,
            event_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            query TEXT NOT NULL,
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            published_at TEXT,
            event_date TEXT NOT NULL,
            country TEXT NOT NULL,
            domain TEXT NOT NULL,
            url TEXT NOT NULL,
            retrieved_at TEXT NOT NULL,
            raw_json TEXT NOT NULL,
            schema_version TEXT NOT NULL,
            PRIMARY KEY (search_id, event_id, provider),
            FOREIGN KEY (search_id) REFERENCES gdelt_searches(search_id) ON DELETE CASCADE
        )
        """
    )
    connection.commit()
    return connection


def save_gdelt_candidates(
    request: GdeltSearchRequest,
    candidates: Iterable[GdeltCandidateRecord],
    *,
    database_path: Path | str = DB_PATH,
) -> int:
    """Persist one search and its normalized candidates idempotently."""
    rows = list(candidates)
    mismatched = [row.event_id for row in rows if row.search_id != request.search_id]
    if mismatched:
        raise ValueError("candidate search_id does not match request search_id")

    with _connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO gdelt_searches (
                search_id, date_start, date_end, query, country, domain,
                result_limit, confidence_profile, sort
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(search_id) DO UPDATE SET
                date_start=excluded.date_start,
                date_end=excluded.date_end,
                query=excluded.query,
                country=excluded.country,
                domain=excluded.domain,
                result_limit=excluded.result_limit,
                confidence_profile=excluded.confidence_profile,
                sort=excluded.sort
            """,
            (
                request.search_id,
                request.date_start,
                request.date_end,
                request.search,
                request.country,
                request.domain,
                request.limit,
                request.confidence_profile,
                request.sort,
            ),
        )
        before = connection.total_changes
        connection.executemany(
            """
            INSERT INTO gdelt_candidates (
                search_id, event_id, provider, query, title, summary,
                published_at, event_date, country, domain, url,
                retrieved_at, raw_json, schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(search_id, event_id, provider) DO UPDATE SET
                query=excluded.query,
                title=excluded.title,
                summary=excluded.summary,
                published_at=excluded.published_at,
                event_date=excluded.event_date,
                country=excluded.country,
                domain=excluded.domain,
                url=excluded.url,
                retrieved_at=excluded.retrieved_at,
                raw_json=excluded.raw_json,
                schema_version=excluded.schema_version
            """,
            [
                (
                    row.search_id,
                    row.event_id,
                    row.provider,
                    row.query,
                    row.title,
                    row.summary,
                    row.published_at,
                    row.event_date,
                    row.country,
                    row.domain,
                    row.url,
                    row.retrieved_at,
                    json.dumps(row.raw, ensure_ascii=False, sort_keys=True),
                    row.schema_version,
                )
                for row in rows
            ],
        )
        connection.commit()
        return connection.total_changes - before


def load_gdelt_candidates(
    search_id: str,
    *,
    database_path: Path | str = DB_PATH,
) -> list[GdeltCandidateRecord]:
    """Load normalized candidates without making another provider request."""
    with _connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT search_id, event_id, provider, query, title, summary,
                   published_at, event_date, country, domain, url,
                   retrieved_at, raw_json, schema_version
            FROM gdelt_candidates
            WHERE search_id = ?
            ORDER BY published_at DESC, event_id
            """,
            (search_id,),
        ).fetchall()

    return [
        GdeltCandidateRecord(
            search_id=row["search_id"],
            event_id=row["event_id"],
            provider=row["provider"],
            query=row["query"],
            title=row["title"],
            summary=row["summary"],
            published_at=row["published_at"],
            event_date=row["event_date"],
            country=row["country"],
            domain=row["domain"],
            url=row["url"],
            retrieved_at=row["retrieved_at"],
            raw=json.loads(row["raw_json"]),
            schema_version=row["schema_version"],
        )
        for row in rows
    ]
