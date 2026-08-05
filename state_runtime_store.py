from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from database import connect
from state_contracts import (
    DecisionStateSnapshot,
    EventContribution,
    InformationStateSnapshot,
    MarketMoverAlert,
    MarketStateSnapshot,
)


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
                CREATE TABLE IF NOT EXISTS decision_state_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    market TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_decision_state_market_as_of
                ON decision_state_snapshots(market, as_of);
                CREATE TABLE IF NOT EXISTS technical_market_state_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    market TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_technical_market_state_market_as_of
                ON technical_market_state_snapshots(market, as_of);
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

    def save_decision_states(self, snapshots: Iterable[DecisionStateSnapshot]) -> int:
        rows = list(snapshots)
        with self._connect() as db:
            for snapshot in rows:
                db.execute(
                    """
                    INSERT INTO decision_state_snapshots(snapshot_id, market, as_of, direction, payload_json)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(snapshot_id) DO UPDATE SET
                        market=excluded.market,
                        as_of=excluded.as_of,
                        direction=excluded.direction,
                        payload_json=excluded.payload_json,
                        recorded_at=CURRENT_TIMESTAMP
                    """,
                    (
                        snapshot.snapshot_id,
                        snapshot.market,
                        snapshot.as_of,
                        snapshot.direction,
                        json.dumps(snapshot.to_record(), ensure_ascii=False, sort_keys=True),
                    ),
                )
        return len(rows)

    def save_market_states(self, snapshots: Iterable[MarketStateSnapshot]) -> int:
        rows = list(snapshots)
        with self._connect() as db:
            for item in rows:
                db.execute(
                    """
                    INSERT INTO technical_market_state_snapshots(snapshot_id, market, as_of, payload_json)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(snapshot_id) DO UPDATE SET
                        payload_json=excluded.payload_json,
                        recorded_at=CURRENT_TIMESTAMP
                    """,
                    (item.snapshot_id, item.market, item.as_of, json.dumps(item.to_record(), sort_keys=True)),
                )
        return len(rows)

    def load_latest_decision_state(self, *, market: str) -> DecisionStateSnapshot | None:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT payload_json
                FROM decision_state_snapshots
                WHERE market=?
                ORDER BY as_of DESC
                LIMIT 1
                """,
                (market,),
            ).fetchone()
        return None if row is None else DecisionStateSnapshot(**json.loads(row["payload_json"]))

    def load_latest_decision_states(self) -> list[DecisionStateSnapshot]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT d.payload_json
                FROM decision_state_snapshots d
                INNER JOIN (
                    SELECT market, MAX(as_of) AS max_as_of
                    FROM decision_state_snapshots
                    GROUP BY market
                ) latest
                ON d.market=latest.market AND d.as_of=latest.max_as_of
                ORDER BY d.market
                """
            ).fetchall()
        return [DecisionStateSnapshot(**json.loads(row["payload_json"])) for row in rows]

    def load_latest_market_state(self, *, market: str) -> MarketStateSnapshot | None:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT payload_json
                FROM technical_market_state_snapshots
                WHERE market=?
                ORDER BY as_of DESC
                LIMIT 1
                """,
                (market,),
            ).fetchone()
        if row is None:
            return None
        record = json.loads(row["payload_json"])
        component = record.get("component")
        if isinstance(component, dict):
            from state_contracts import ComponentStatus

            record["component"] = ComponentStatus(**component)
        return MarketStateSnapshot(**record)

    def has_contribution(self, *, event_id: str, market: str) -> bool:
        with self._connect() as db:
            row = db.execute(
                "SELECT 1 AS present FROM event_contributions WHERE event_id=? AND market=?",
                (str(event_id), str(market)),
            ).fetchone()
        return row is not None

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

    def load_latest_information_snapshot(self) -> InformationStateSnapshot | None:
        record = self.load_latest_information_state()
        if record is None:
            return None
        component = record.get("component")
        if isinstance(component, dict):
            from state_contracts import ComponentStatus

            record["component"] = ComponentStatus(**component)
        for name in ("source_channels", "processed_event_ids", "active_cluster_ids"):
            record[name] = tuple(record.get(name) or ())
        return InformationStateSnapshot(**record)
