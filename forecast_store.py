from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from database import connect
from forecast_contracts import FORECAST_ENGINE_VERSION, ForecastSnapshot


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
                DROP INDEX IF EXISTS idx_forecast_decision_snapshot;
                CREATE INDEX IF NOT EXISTS idx_forecast_decision_snapshot
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

    @staticmethod
    def _from_payload(payload_json: str) -> ForecastSnapshot | None:
        record = json.loads(payload_json)
        if str(record.get("engine_version") or "") != FORECAST_ENGINE_VERSION:
            return None
        record["missing_inputs"] = tuple(record.get("missing_inputs") or ())
        return ForecastSnapshot(**record)

    def load_all(
        self,
        *,
        market: str | None = None,
        horizon_hours: float | None = None,
        limit: int = 500,
    ) -> list[ForecastSnapshot]:
        query = "SELECT payload_json FROM forecast_snapshots"
        params: list[object] = []
        if market:
            query += " WHERE market=?"
            params.append(market)
        query += " ORDER BY as_of DESC, recorded_at DESC, forecast_id DESC LIMIT ?"
        params.append(max(1, int(limit)))
        with self._connect() as db:
            rows = db.execute(query, tuple(params)).fetchall()
        snapshots: list[ForecastSnapshot] = []
        for row in rows:
            snapshot = self._from_payload(row["payload_json"])
            if snapshot is None:
                continue
            if horizon_hours is not None:
                if snapshot.horizon_hours is None or abs(float(snapshot.horizon_hours) - float(horizon_hours)) > 1e-6:
                    continue
            snapshots.append(snapshot)
        return snapshots

    def load_latest(self, *, market: str, horizon_hours: float | None = None) -> ForecastSnapshot | None:
        for snapshot in self.load_all(market=market, horizon_hours=horizon_hours, limit=1000):
            return snapshot
        return None

    def load_latest_all(self) -> list[ForecastSnapshot]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT payload_json
                FROM forecast_snapshots
                ORDER BY market, as_of DESC, recorded_at DESC, forecast_id DESC
                """
            ).fetchall()
        latest: dict[tuple[str, float | None], ForecastSnapshot] = {}
        for row in rows:
            snapshot = self._from_payload(row["payload_json"])
            if snapshot is None:
                continue
            key = (snapshot.market, snapshot.horizon_hours)
            if key not in latest:
                latest[key] = snapshot
        return [latest[key] for key in sorted(latest, key=lambda item: (item[0], float("inf") if item[1] is None else item[1]))]
