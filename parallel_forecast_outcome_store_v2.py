from __future__ import annotations

import json
from pathlib import Path

from database import connect
from parallel_forecast_outcome_v2 import ParallelForecastOutcomeV2


class ParallelForecastOutcomeStoreV2:
    """Freeze one realized outcome per outcome_key plus immutable candidate scores."""

    def __init__(self, path: str | Path = "pricegauger.db") -> None:
        self.path = str(path)
        with connect(self.path) as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS pg_v2_parallel_forecast_outcomes (
                    outcome_key TEXT PRIMARY KEY,
                    market TEXT NOT NULL,
                    forecast_as_of TEXT NOT NULL,
                    horizon_seconds INTEGER NOT NULL,
                    matured_at TEXT NOT NULL,
                    reference_price REAL NOT NULL,
                    realized_terminal_price REAL NOT NULL,
                    realized_return REAL NOT NULL,
                    payload_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS pg_v2_parallel_forecast_scores (
                    outcome_key TEXT NOT NULL,
                    candidate_kind TEXT NOT NULL,
                    predicted_return REAL NOT NULL,
                    realized_return REAL NOT NULL,
                    signed_error REAL NOT NULL,
                    absolute_error REAL NOT NULL,
                    direction_hit INTEGER NOT NULL,
                    interval_hit INTEGER NOT NULL,
                    PRIMARY KEY(outcome_key, candidate_kind)
                );
                """
            )

    def save(self, outcome: ParallelForecastOutcomeV2) -> bool:
        payload = json.dumps(outcome.to_record(), sort_keys=True, separators=(",", ":"))
        with connect(self.path) as db:
            cursor = db.execute(
                """
                INSERT INTO pg_v2_parallel_forecast_outcomes(
                    outcome_key, market, forecast_as_of, horizon_seconds, matured_at,
                    reference_price, realized_terminal_price, realized_return, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(outcome_key) DO NOTHING
                """,
                (
                    outcome.outcome_key,
                    outcome.market,
                    outcome.forecast_as_of,
                    outcome.horizon_seconds,
                    outcome.matured_at,
                    outcome.reference_price,
                    outcome.realized_terminal_price,
                    outcome.realized_return,
                    payload,
                ),
            )
            inserted = bool(getattr(cursor, "rowcount", 0))
            for score in (outcome.technical, outcome.technical_context):
                db.execute(
                    """
                    INSERT INTO pg_v2_parallel_forecast_scores(
                        outcome_key, candidate_kind, predicted_return, realized_return,
                        signed_error, absolute_error, direction_hit, interval_hit
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(outcome_key, candidate_kind) DO NOTHING
                    """,
                    (
                        outcome.outcome_key,
                        score.candidate_kind,
                        score.predicted_return,
                        score.realized_return,
                        score.signed_error,
                        score.absolute_error,
                        int(score.direction_hit),
                        int(score.interval_hit),
                    ),
                )
        return inserted

    def is_resolved(self, outcome_key: str) -> bool:
        with connect(self.path) as db:
            row = db.execute(
                "SELECT 1 AS present FROM pg_v2_parallel_forecast_outcomes WHERE outcome_key=? LIMIT 1",
                (outcome_key,),
            ).fetchone()
        return row is not None
