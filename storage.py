from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

from event_models import MarketEvent
from event_reactions import EventReaction

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
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS event_market_reactions (
            event_id TEXT NOT NULL,
            asset TEXT NOT NULL,
            symbol TEXT NOT NULL,
            event_date TEXT NOT NULL,
            base_date TEXT NOT NULL,
            base_close REAL NOT NULL,
            return_1d_pct REAL,
            return_3d_pct REAL,
            return_5d_pct REAL,
            max_up_5d_pct REAL,
            max_down_5d_pct REAL,
            calculated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (event_id, asset),
            FOREIGN KEY (event_id) REFERENCES events(event_id)
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


def save_reactions(reactions: Iterable[EventReaction]) -> int:
    rows = list(reactions)
    if not rows:
        return 0
    with connect() as connection:
        before = connection.total_changes
        connection.executemany(
            """
            INSERT INTO event_market_reactions (
                event_id, asset, symbol, event_date, base_date, base_close,
                return_1d_pct, return_3d_pct, return_5d_pct,
                max_up_5d_pct, max_down_5d_pct
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_id, asset) DO UPDATE SET
                symbol=excluded.symbol,
                event_date=excluded.event_date,
                base_date=excluded.base_date,
                base_close=excluded.base_close,
                return_1d_pct=excluded.return_1d_pct,
                return_3d_pct=excluded.return_3d_pct,
                return_5d_pct=excluded.return_5d_pct,
                max_up_5d_pct=excluded.max_up_5d_pct,
                max_down_5d_pct=excluded.max_down_5d_pct,
                calculated_at=CURRENT_TIMESTAMP
            """,
            [
                (
                    row.event_id, row.asset, row.symbol, row.event_date,
                    row.base_date, row.base_close, row.return_1d_pct,
                    row.return_3d_pct, row.return_5d_pct,
                    row.max_up_5d_pct, row.max_down_5d_pct,
                )
                for row in rows
            ],
        )
        connection.commit()
        return connection.total_changes - before
