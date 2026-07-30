from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from database import connect
from state_contracts import EventContribution, InformationStateSnapshot, MarketMoverAlert


class StateRuntimeStore:
    """Persistent storage for the authoritative state-oriented runtime."""

    def __init__(self, path: str | Path = "pricegauger.db") -> None:
        self.path = str(path)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS information_state_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    as_of TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS event_contributions (
                    event_id TEXT NOT NULL,
                    event_cluster_id TEXT NOT NULL,
                    market TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY (event_id, market)
                );
                CREATE TABLE IF NOT EXISTS market_mover_alerts (
                    alert_id TEXT PRIMARY KEY,
                    event_cluster_id TEXT NOT NULL,
                    market TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                """
            )

    def _connect(self):
        return connect(self.path)

    def save_information_state(self, snapshot: InformationStateSnapshot) -> None:
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO information_state_snapshots(snapshot_id, as_of, payload_json)
                VALUES (?, ?, ?)
                ON CONFLICT(snapshot_id) DO UPDATE SET
                    as_of=excluded.as_of,
                    payload_json=excluded.payload_json,
                    recorded_at=CURRENT_TIMESTAMP
                """,
                (snapshot.snapshot_id, snapshot.as_of, json.dumps(snapshot.to_record(), ensure_ascii=False, sort_keys=True)),
            )

    def save_contributions(self, items: Iterable[EventContribution]) -> int:
        rows = list(items)
        with self._connect() as db:
            for item in rows:
                db.execute(
                    """
                    INSERT INTO event_contributions(event_id, event_cluster_id, market, observed_at, payload_json)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(event_id, market) DO UPDATE SET
                        event_cluster_id=excluded.event_cluster_id,
                        observed_at=excluded.observed_at,
                        payload_json=excluded.payload_json
                    """,
                    (
                        item.event_id,
                        item.event_cluster_id,
                        item.market,
                        item.observed_at,
                        json.dumps(item.to_record(), ensure_ascii=False, sort_keys=True),
                    ),
                )
        return len(rows)

    def save_alert(self, alert: MarketMoverAlert) -> None:
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO market_mover_alerts(
                    alert_id, event_cluster_id, market, severity, status, updated_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(alert_id) DO UPDATE SET
                    severity=excluded.severity,
                    status=excluded.status,
                    updated_at=excluded.updated_at,
                    payload_json=excluded.payload_json
                """,
                (
                    alert.alert_id,
                    alert.event_cluster_id,
                    alert.market,
                    alert.severity,
                    alert.status,
                    alert.updated_at,
                    json.dumps(alert.to_record(), ensure_ascii=False, sort_keys=True),
                ),
            )

    def load_latest_alert(self, *, market: str | None = None) -> MarketMoverAlert | None:
        query = "SELECT payload_json FROM market_mover_alerts"
        params: tuple[object, ...] = ()
        if market:
            query += " WHERE market=?"
            params = (market,)
        query += " ORDER BY updated_at DESC LIMIT 1"
        with self._connect() as db:
            row = db.execute(query, params).fetchone()
        return None if row is None else MarketMoverAlert(**json.loads(row["payload_json"]))

    def load_latest_information_state(self) -> dict | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT payload_json FROM information_state_snapshots ORDER BY as_of DESC LIMIT 1"
            ).fetchone()
        return None if row is None else json.loads(row["payload_json"])
