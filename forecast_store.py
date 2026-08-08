from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from database import connect
from forecast_contracts import ForecastSnapshot


class ForecastStore:
    def __init__(self, path: str | Path = "pricegauger.db") -> None:
        self.path = str(path)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS forecast_snapshots (
                    forecast_id TEXT PRIMARY KEY,
                    market TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    status TEXT NOT NULL,
                    decision_snapshot_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_forecast_market_as_of
                ON forecast_snapshots(market, as_of);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_forecast_decision_snapshot
                ON forecast_snapshots(decision_snapshot_id);
                """
            )

    def _connect(self):
        return connect(self.path)

    def save(self, snapshot: ForecastSnapshot) -> None:
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO forecast_snapshots(
                    forecast_id, market, as_of, status, decision_snapshot_id, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(forecast_id) DO UPDATE SET
                    market=excluded.market,
                    as_of=excluded.as_of,
                    status=excluded.status,
                    decision_snapshot_id=excluded.decision_snapshot_id,
                    payload_json=excluded.payload_json,
                    recorded_at=CURRENT_TIMESTAMP
                """,
                (
                    snapshot.forecast_id,
                    snapshot.market,
                    snapshot.as_of,
                    snapshot.status,
                    snapshot.decision_snapshot_id,
                    json.dumps(snapshot.to_record(), ensure_ascii=False, sort_keys=True),
                ),
            )

    def save_all(self, snapshots: Iterable[ForecastSnapshot]) -> int:
        rows = list(snapshots)
        for snapshot in rows:
            self.save(snapshot)
        return len(rows)

    def load_latest(self, *, market: str) -> ForecastSnapshot | None:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT payload_json
                FROM forecast_snapshots
                WHERE market=?
                ORDER BY as_of DESC
                LIMIT 1
                """,
                (market,),
            ).fetchone()
        if row is None:
            return None
        record = json.loads(row["payload_json"])
        record["missing_inputs"] = tuple(record.get("missing_inputs") or ())
        return ForecastSnapshot(**record)

    def load_latest_all(self) -> list[ForecastSnapshot]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT f.payload_json
                FROM forecast_snapshots f
                INNER JOIN (
                    SELECT market, MAX(as_of) AS max_as_of
                    FROM forecast_snapshots
                    GROUP BY market
                ) latest
                ON f.market=latest.market AND f.as_of=latest.max_as_of
                ORDER BY f.market
                """
            ).fetchall()
        result: list[ForecastSnapshot] = []
        for row in rows:
            record = json.loads(row["payload_json"])
            record["missing_inputs"] = tuple(record.get("missing_inputs") or ())
            result.append(ForecastSnapshot(**record))
        return result
