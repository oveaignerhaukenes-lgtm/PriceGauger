from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

from event_models import MarketEvent
from signal_aggregator import build_event_signals
from signal_store import SignalStore


def _load_events(database_path: str | Path) -> list[MarketEvent]:
    path = Path(database_path)
    if not path.exists():
        return []

    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT event_id, source, event_date, published_at, timestamp_source,
                   timestamp_confidence, title, summary, category, subcategory,
                   domain, country, location, actors_json, confidence,
                   market_sensitivity, significance, url, raw_json
            FROM events
            ORDER BY COALESCE(published_at, event_date)
            """
        ).fetchall()

    events: list[MarketEvent] = []
    for row in rows:
        try:
            actors = json.loads(row["actors_json"] or "[]")
        except json.JSONDecodeError:
            actors = []
        try:
            raw = json.loads(row["raw_json"] or "{}")
        except json.JSONDecodeError:
            raw = {}
        events.append(
            MarketEvent(
                event_id=str(row["event_id"] or ""),
                source=str(row["source"] or ""),
                event_date=str(row["event_date"] or ""),
                title=str(row["title"] or ""),
                summary=str(row["summary"] or ""),
                category=str(row["category"] or ""),
                subcategory=str(row["subcategory"] or ""),
                domain=str(row["domain"] or ""),
                country=str(row["country"] or ""),
                location=str(row["location"] or ""),
                actors=actors if isinstance(actors, list) else [],
                confidence=row["confidence"],
                market_sensitivity=row["market_sensitivity"],
                significance=row["significance"],
                url=str(row["url"] or ""),
                raw=raw if isinstance(raw, dict) else {},
                published_at=row["published_at"],
                timestamp_source=row["timestamp_source"],
                timestamp_confidence=row["timestamp_confidence"],
            )
        )
    return events


def persist_finished_signals(
    *,
    database_path: str | Path,
    reactions: Iterable[object],
    window_hours: int = 24,
    half_life_hours: float = 6.0,
    minimum_similarity: float = 0.20,
) -> int:
    """Persist completed EventSignals after Historical Event Lab has saved reactions.

    This is the explicit boundary between historical analysis and short-term market
    memory. The SignalStore receives finished signals only; aggregation happens later.
    """
    reaction_list = list(reactions)
    if not reaction_list:
        return 0

    events = _load_events(database_path)
    if not events:
        return 0

    assets = sorted(
        {
            str(getattr(reaction, "asset", "") or "").strip()
            for reaction in reaction_list
            if str(getattr(reaction, "asset", "") or "").strip()
        }
    )
    store = SignalStore()
    stored = 0
    for asset in assets:
        signals = build_event_signals(
            events=events,
            reactions=reaction_list,
            asset=asset,
            window_hours=window_hours,
            half_life_hours=half_life_hours,
            minimum_similarity=minimum_similarity,
        )
        stored += store.add_many(signals)

    store.purge_expired()
    return stored
