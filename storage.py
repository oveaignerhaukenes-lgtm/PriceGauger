from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

from event_models import MarketEvent
from signal_persistence import persist_finished_signals

if TYPE_CHECKING:
    from event_reactions import EventReaction
    from intraday_reactions import IntradayReaction

DB_PATH = Path("data/pricegauger.db")


def _ensure_columns(
    connection: sqlite3.Connection,
    table: str,
    additions: dict[str, str],
) -> None:
    existing = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    for name, column_type in additions.items():
        if name not in existing:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {column_type}")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            event_date TEXT,
            published_at TEXT,
            timestamp_source TEXT,
            timestamp_confidence REAL,
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
    _ensure_columns(
        connection,
        "events",
        {
            "published_at": "TEXT",
            "timestamp_source": "TEXT",
            "timestamp_confidence": "REAL",
        },
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
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS event_intraday_reactions (
            event_id TEXT NOT NULL,
            event_title TEXT,
            asset TEXT NOT NULL,
            symbol TEXT NOT NULL,
            published_at TEXT NOT NULL,
            interval TEXT NOT NULL,
            anchor_time TEXT NOT NULL,
            anchor_lag_minutes REAL NOT NULL,
            market_state TEXT,
            base_price REAL NOT NULL,
            return_5m_pct REAL,
            return_15m_pct REAL,
            return_30m_pct REAL,
            return_1h_pct REAL,
            return_4h_pct REAL,
            return_24h_pct REAL,
            bar_time_5m TEXT,
            bar_time_15m TEXT,
            bar_time_30m TEXT,
            bar_time_1h TEXT,
            bar_time_4h TEXT,
            bar_time_24h TEXT,
            distinct_window_bars INTEGER,
            duplicate_group_size INTEGER,
            quality_score REAL,
            max_up_24h_pct REAL,
            max_down_24h_pct REAL,
            time_to_max_minutes REAL,
            time_to_min_minutes REAL,
            calculated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (event_id, asset),
            FOREIGN KEY (event_id) REFERENCES events(event_id)
        )
        """
    )
    _ensure_columns(
        connection,
        "event_intraday_reactions",
        {
            "event_title": "TEXT",
            "market_state": "TEXT",
            "bar_time_5m": "TEXT",
            "bar_time_15m": "TEXT",
            "bar_time_30m": "TEXT",
            "bar_time_1h": "TEXT",
            "bar_time_4h": "TEXT",
            "bar_time_24h": "TEXT",
            "distinct_window_bars": "INTEGER",
            "duplicate_group_size": "INTEGER",
            "quality_score": "REAL",
        },
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
                event_id, source, event_date, published_at, timestamp_source,
                timestamp_confidence, title, summary, category, subcategory,
                domain, country, location, actors_json, confidence,
                market_sensitivity, significance, url, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_id) DO UPDATE SET
                event_date=excluded.event_date,
                published_at=excluded.published_at,
                timestamp_source=excluded.timestamp_source,
                timestamp_confidence=excluded.timestamp_confidence,
                title=excluded.title,
                summary=excluded.summary,
                confidence=excluded.confidence,
                market_sensitivity=excluded.market_sensitivity,
                significance=excluded.significance,
                raw_json=excluded.raw_json
            """,
            [
                (
                    event.event_id,
                    event.source,
                    event.event_date,
                    event.published_at,
                    event.timestamp_source,
                    event.timestamp_confidence,
                    event.title,
                    event.summary,
                    event.category,
                    event.subcategory,
                    event.domain,
                    event.country,
                    event.location,
                    json.dumps(event.actors, ensure_ascii=False),
                    event.confidence,
                    event.market_sensitivity,
                    event.significance,
                    event.url,
                    json.dumps(event.raw, ensure_ascii=False),
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
                    row.event_id,
                    row.asset,
                    row.symbol,
                    row.event_date,
                    row.base_date,
                    row.base_close,
                    row.return_1d_pct,
                    row.return_3d_pct,
                    row.return_5d_pct,
                    row.max_up_5d_pct,
                    row.max_down_5d_pct,
                )
                for row in rows
            ],
        )
        connection.commit()
        return connection.total_changes - before


def save_intraday_reactions(reactions: Iterable[IntradayReaction]) -> int:
    rows = list(reactions)
    if not rows:
        return 0
    with connect() as connection:
        before = connection.total_changes
        connection.executemany(
            """
            INSERT INTO event_intraday_reactions (
                event_id, event_title, asset, symbol, published_at, interval,
                anchor_time, anchor_lag_minutes, market_state, base_price,
                return_5m_pct, return_15m_pct, return_30m_pct, return_1h_pct,
                return_4h_pct, return_24h_pct, bar_time_5m, bar_time_15m,
                bar_time_30m, bar_time_1h, bar_time_4h, bar_time_24h,
                distinct_window_bars, duplicate_group_size, quality_score,
                max_up_24h_pct, max_down_24h_pct, time_to_max_minutes,
                time_to_min_minutes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_id, asset) DO UPDATE SET
                event_title=excluded.event_title,
                symbol=excluded.symbol,
                published_at=excluded.published_at,
                interval=excluded.interval,
                anchor_time=excluded.anchor_time,
                anchor_lag_minutes=excluded.anchor_lag_minutes,
                market_state=excluded.market_state,
                base_price=excluded.base_price,
                return_5m_pct=excluded.return_5m_pct,
                return_15m_pct=excluded.return_15m_pct,
                return_30m_pct=excluded.return_30m_pct,
                return_1h_pct=excluded.return_1h_pct,
                return_4h_pct=excluded.return_4h_pct,
                return_24h_pct=excluded.return_24h_pct,
                bar_time_5m=excluded.bar_time_5m,
                bar_time_15m=excluded.bar_time_15m,
                bar_time_30m=excluded.bar_time_30m,
                bar_time_1h=excluded.bar_time_1h,
                bar_time_4h=excluded.bar_time_4h,
                bar_time_24h=excluded.bar_time_24h,
                distinct_window_bars=excluded.distinct_window_bars,
                duplicate_group_size=excluded.duplicate_group_size,
                quality_score=excluded.quality_score,
                max_up_24h_pct=excluded.max_up_24h_pct,
                max_down_24h_pct=excluded.max_down_24h_pct,
                time_to_max_minutes=excluded.time_to_max_minutes,
                time_to_min_minutes=excluded.time_to_min_minutes,
                calculated_at=CURRENT_TIMESTAMP
            """,
            [
                (
                    row.event_id,
                    row.event_title,
                    row.asset,
                    row.symbol,
                    row.published_at,
                    row.interval,
                    row.anchor_time,
                    row.anchor_lag_minutes,
                    row.market_state,
                    row.base_price,
                    row.return_5m_pct,
                    row.return_15m_pct,
                    row.return_30m_pct,
                    row.return_1h_pct,
                    row.return_4h_pct,
                    row.return_24h_pct,
                    row.bar_time_5m,
                    row.bar_time_15m,
                    row.bar_time_30m,
                    row.bar_time_1h,
                    row.bar_time_4h,
                    row.bar_time_24h,
                    row.distinct_window_bars,
                    row.duplicate_group_size,
                    row.quality_score,
                    row.max_up_24h_pct,
                    row.max_down_24h_pct,
                    row.time_to_max_minutes,
                    row.time_to_min_minutes,
                )
                for row in rows
            ],
        )
        connection.commit()
        changes = connection.total_changes - before

    persist_finished_signals(database_path=DB_PATH, reactions=rows)
    return changes
