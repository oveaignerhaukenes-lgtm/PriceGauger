from __future__ import annotations

import json
from pathlib import Path

from database import connect
from overview_summary_contract import OverviewSummary


class OverviewSummaryStore:
    def __init__(self, path: str | Path = "pricegauger.db") -> None:
        self.path = str(path)
        with connect(self.path) as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS overview_summaries (
                    information_snapshot_id TEXT PRIMARY KEY,
                    as_of TEXT NOT NULL,
                    model TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_overview_summaries_as_of
                ON overview_summaries(as_of);
                """
            )

    def save(self, *, information_snapshot_id: str, as_of: str, summary: OverviewSummary) -> None:
        with connect(self.path) as db:
            db.execute(
                """
                INSERT INTO overview_summaries(information_snapshot_id, as_of, model, payload_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(information_snapshot_id) DO UPDATE SET
                    as_of=excluded.as_of,
                    model=excluded.model,
                    payload_json=excluded.payload_json,
                    recorded_at=CURRENT_TIMESTAMP
                """,
                (
                    information_snapshot_id,
                    as_of,
                    summary.model,
                    json.dumps(summary.to_record(), ensure_ascii=False, sort_keys=True),
                ),
            )

    def load_latest(self) -> OverviewSummary | None:
        with connect(self.path) as db:
            row = db.execute(
                "SELECT payload_json FROM overview_summaries ORDER BY as_of DESC LIMIT 1"
            ).fetchone()
        return None if row is None else OverviewSummary(**json.loads(row["payload_json"]))
