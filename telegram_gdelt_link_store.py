from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from storage import DB_PATH
from telegram_query_builder import TelegramSearchPlan


@dataclass(frozen=True, slots=True)
class TelegramGdeltSearchLink:
    message_id: str
    message_url: str
    message_text: str
    published_at: str
    search_id: str
    created_at: str


def _connect(database_path: Path | str = DB_PATH) -> sqlite3.Connection:
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS telegram_gdelt_searches (
            message_id TEXT NOT NULL,
            search_id TEXT NOT NULL,
            message_url TEXT NOT NULL,
            message_text TEXT NOT NULL,
            published_at TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (message_id, search_id),
            FOREIGN KEY (search_id) REFERENCES gdelt_searches(search_id) ON DELETE CASCADE
        )
        """
    )
    connection.commit()
    return connection


def save_telegram_gdelt_search_link(
    plan: TelegramSearchPlan,
    search_id: str,
    *,
    database_path: Path | str = DB_PATH,
) -> None:
    """Persist the Telegram-message to GDELT-search relationship idempotently."""
    if not plan.message_id.strip():
        raise ValueError("Telegram plan has no message_id")
    if not search_id.strip():
        raise ValueError("GDELT search_id is required")

    with _connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO telegram_gdelt_searches (
                message_id, search_id, message_url, message_text, published_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(message_id, search_id) DO UPDATE SET
                message_url=excluded.message_url,
                message_text=excluded.message_text,
                published_at=excluded.published_at
            """,
            (
                plan.message_id,
                search_id,
                plan.message_url,
                plan.message_text,
                plan.published_at,
            ),
        )
        connection.commit()


def load_telegram_gdelt_search_links(
    message_id: str,
    *,
    database_path: Path | str = DB_PATH,
) -> list[TelegramGdeltSearchLink]:
    """Load stored GDELT searches for one Telegram message without new API calls."""
    with _connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT message_id, message_url, message_text, published_at,
                   search_id, created_at
            FROM telegram_gdelt_searches
            WHERE message_id = ?
            ORDER BY created_at DESC, search_id
            """,
            (message_id,),
        ).fetchall()

    return [
        TelegramGdeltSearchLink(
            message_id=row["message_id"],
            message_url=row["message_url"],
            message_text=row["message_text"],
            published_at=row["published_at"],
            search_id=row["search_id"],
            created_at=row["created_at"],
        )
        for row in rows
    ]
