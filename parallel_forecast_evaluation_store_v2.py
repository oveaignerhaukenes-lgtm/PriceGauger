from __future__ import annotations

import json
from pathlib import Path

from database import connect
from parallel_forecast_evaluation_v2 import ParallelForecastExperimentV2


class ParallelForecastEvaluationStoreV2:
    """Persist immutable paired forecast benchmarks for later outcome resolution."""

    def __init__(self, path: str | Path = "pricegauger.db") -> None:
        self.path = str(path)
        with connect(self.path) as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS pg_v2_forecast_experiments (
                    experiment_id TEXT PRIMARY KEY,
                    outcome_key TEXT NOT NULL,
                    market TEXT NOT NULL,
                    forecast_as_of TEXT NOT NULL,
                    horizon_seconds INTEGER NOT NULL,
                    evaluation_version TEXT NOT NULL,
                    context_snapshot_id TEXT NOT NULL,
                    context_fingerprint TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_pg_v2_forecast_outcome_key
                    ON pg_v2_forecast_experiments(outcome_key);
                """
            )

    def save(self, experiment: ParallelForecastExperimentV2) -> bool:
        payload = json.dumps(experiment.to_record(), sort_keys=True, separators=(",", ":"))
        with connect(self.path) as db:
            cursor = db.execute(
                """
                INSERT INTO pg_v2_forecast_experiments(
                    experiment_id, outcome_key, market, forecast_as_of,
                    horizon_seconds, evaluation_version, context_snapshot_id,
                    context_fingerprint, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(experiment_id) DO NOTHING
                """,
                (
                    experiment.experiment_id,
                    experiment.outcome_key,
                    experiment.market,
                    experiment.forecast_as_of,
                    experiment.horizon_seconds,
                    experiment.evaluation_version,
                    experiment.context_snapshot_id,
                    experiment.context_fingerprint,
                    payload,
                ),
            )
            return bool(getattr(cursor, "rowcount", 0))

    def count_for_outcome(self, outcome_key: str) -> int:
        with connect(self.path) as db:
            row = db.execute(
                "SELECT COUNT(*) AS n FROM pg_v2_forecast_experiments WHERE outcome_key=?",
                (outcome_key,),
            ).fetchone()
        return int(row["n"])
