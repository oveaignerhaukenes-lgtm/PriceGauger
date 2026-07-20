from __future__ import annotations

import json
import sqlite3
from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

from signal_aggregator import EventSignal


DEFAULT_SIGNAL_DB = Path("data/signals.sqlite3")


class SignalStore:
    """Persistent store for finished EventSignal objects.

    The store deliberately knows nothing about EventDNA, historical matching, GDELT,
    Telegram, or decision rules. It only persists and retrieves completed signals.
    """

    def __init__(self, path: str | Path = DEFAULT_SIGNAL_DB) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._create_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _create_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS event_signals (
                    event_id TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    stored_at TEXT NOT NULL,
                    PRIMARY KEY (event_id, asset)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_event_signals_asset_time "
                "ON event_signals(asset, published_at)"
            )

    def add(self, signal: EventSignal) -> None:
        payload = json.dumps(signal.to_record(), ensure_ascii=False, sort_keys=True)
        stored_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO event_signals(event_id, asset, published_at, payload, stored_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(event_id, asset) DO UPDATE SET
                    published_at = excluded.published_at,
                    payload = excluded.payload,
                    stored_at = excluded.stored_at
                """,
                (signal.event_id, signal.asset, signal.published_at, payload, stored_at),
            )

    def add_many(self, signals: Iterable[EventSignal]) -> int:
        count = 0
        for signal in signals:
            self.add(signal)
            count += 1
        return count

    def all(self, asset: str | None = None) -> list[EventSignal]:
        query = "SELECT payload FROM event_signals"
        params: tuple[str, ...] = ()
        if asset:
            query += " WHERE asset = ?"
            params = (asset,)
        query += " ORDER BY published_at DESC"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._decode(row["payload"]) for row in rows]

    def active(
        self,
        asset: str,
        *,
        window_hours: float | None = None,
        now: pd.Timestamp | None = None,
    ) -> list[EventSignal]:
        current = now or pd.Timestamp.now(tz="UTC")
        if current.tzinfo is None:
            current = current.tz_localize("UTC")
        else:
            current = current.tz_convert("UTC")

        active_signals: list[EventSignal] = []
        for signal in self.all(asset):
            timestamp = pd.to_datetime(signal.published_at, utc=True, errors="coerce")
            if pd.isna(timestamp):
                continue
            age_hours = max(0.0, (current - timestamp).total_seconds() / 3600.0)
            maximum_age = float(signal.max_age_hours)
            if window_hours is not None:
                maximum_age = min(maximum_age, float(window_hours))
            if age_hours <= maximum_age:
                active_signals.append(signal)
        return active_signals

    def purge_expired(self, *, now: pd.Timestamp | None = None) -> int:
        expired = []
        current = now or pd.Timestamp.now(tz="UTC")
        for signal in self.all():
            timestamp = pd.to_datetime(signal.published_at, utc=True, errors="coerce")
            if pd.isna(timestamp):
                expired.append((signal.event_id, signal.asset))
                continue
            age_hours = max(0.0, (current - timestamp).total_seconds() / 3600.0)
            if age_hours > float(signal.max_age_hours):
                expired.append((signal.event_id, signal.asset))

        with self._connect() as connection:
            connection.executemany(
                "DELETE FROM event_signals WHERE event_id = ? AND asset = ?",
                expired,
            )
        return len(expired)

    def remove(self, event_id: str, asset: str | None = None) -> int:
        with self._connect() as connection:
            if asset is None:
                cursor = connection.execute(
                    "DELETE FROM event_signals WHERE event_id = ?", (event_id,)
                )
            else:
                cursor = connection.execute(
                    "DELETE FROM event_signals WHERE event_id = ? AND asset = ?",
                    (event_id, asset),
                )
        return int(cursor.rowcount)

    @staticmethod
    def _decode(payload: str) -> EventSignal:
        record = json.loads(payload)
        allowed = {field.name for field in fields(EventSignal)}
        return EventSignal(**{key: value for key, value in record.items() if key in allowed})
