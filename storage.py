from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

from event_models import MarketEvent

DB_PATH = Path("data/pricegauger.db")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            event_date TEXT,
            title TEXT,
            summary TEXT,
            category TEXT,
            subcategory TEXT,
            domain TEXT,
            country TEXT,
            location TEXT,
            actors_json TEXT,
            confidence REAL,
            market_sensitivity REAL,
            significance REAL,
            url TEXT,
            raw_json TEXT NOT NULL,
            collected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.commit()
    return connection


def save_events(events: Iterable[MarketEvent]) -> int:
    rows = list(events)
    if not rows:
        return 0
    with connect() as connection:
        before = connection.total_changes
        connection.executemany(
            """
            INSERT INTO events (
                event_id, source, event_date, title, summary, category,
                subcategory, domain, country, location, actors_json,
                confidence, market_sensitivity, significance, url, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_id) DO UPDATE SET
                title=excluded.title,
                summary=excluded.summary,
                confidence=excluded.confidence,
                market_sensitivity=excluded.market_sensitivity,
                significance=excluded.significance,
                raw_json=excluded.raw_json
            """,
            [
                (
                    event.event_id, event.source, event.event_date, event.title,
                    event.summary, event.category, event.subcategory, event.domain,
                    event.country, event.location, json.dumps(event.actors, ensure_ascii=False),
                    event.confidence, event.market_sensitivity, event.significance,
                    event.url, json.dumps(event.raw, ensure_ascii=False),
                )
                for event in rows
            ],
        )
        connection.commit()
        return connection.total_changes - before
