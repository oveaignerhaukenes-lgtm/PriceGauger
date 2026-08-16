from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json

from context_snapshot_store_v2 import ContextSnapshotStoreV2
from database import connect
from market_history_store import MarketHistoryStore
from parallel_forecast_evaluation_store_v2 import ParallelForecastEvaluationStoreV2
from parallel_forecast_evaluation_v2 import ForecastCandidateV2, ParallelForecastExperimentV2, build_parallel_forecast_experiment_v2
from parallel_forecast_outcome_store_v2 import ParallelForecastOutcomeStoreV2
from parallel_forecast_outcome_v2 import evaluate_parallel_forecast_experiment_v2
from runtime_technical_producer_v2 import ProducedTechnicalRuntimeV2


@dataclass(frozen=True, slots=True)
class ParallelForecastRuntimeSummaryV2:
    experiments_attempted: int
    experiments_inserted: int
    outcomes_resolved: int


def _experiment_from_record(record: dict) -> ParallelForecastExperimentV2:
    return ParallelForecastExperimentV2(
        experiment_id=record["experiment_id"],
        outcome_key=record["outcome_key"],
        market=record["market"],
        forecast_as_of=record["forecast_as_of"],
        horizon_seconds=int(record["horizon_seconds"]),
        evaluation_version=record["evaluation_version"],
        technical=ForecastCandidateV2(**record["technical"]),
        technical_context=ForecastCandidateV2(**record["technical_context"]),
        context_snapshot_id=record["context_snapshot_id"],
        context_fingerprint=record["context_fingerprint"],
    )


def load_unresolved_parallel_experiments_v2(
    *, db_path: str = "pricegauger.db", limit: int = 500
) -> tuple[ParallelForecastExperimentV2, ...]:
    with connect(db_path) as db:
        rows = db.execute(
            """
            SELECT e.payload_json
            FROM pg_v2_forecast_experiments e
            LEFT JOIN pg_v2_parallel_forecast_outcomes o ON o.outcome_key = e.outcome_key
            WHERE o.outcome_key IS NULL
            ORDER BY e.forecast_as_of ASC, e.horizon_seconds ASC
            LIMIT ?
            """,
            (max(1, int(limit)),),
        ).fetchall()
    return tuple(_experiment_from_record(json.loads(row["payload_json"])) for row in rows)


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def record_parallel_experiments_v2(
    produced: ProducedTechnicalRuntimeV2,
    *,
    db_path: str = "pricegauger.db",
    scope_key: str = "global",
) -> tuple[int, int]:
    context = ContextSnapshotStoreV2(db_path).load_latest(scope_key=scope_key)
    if context is None:
        return 0, 0
    store = ParallelForecastEvaluationStoreV2(db_path)
    attempted = inserted = 0
    for baseline in produced.baselines.values():
        attempted += 1
        experiment = build_parallel_forecast_experiment_v2(technical=baseline, context=context)
        if store.save(experiment):
            inserted += 1
    return attempted, inserted


def resolve_parallel_outcomes_v2(
    *,
    history_store: MarketHistoryStore,
    db_path: str = "pricegauger.db",
    limit: int = 500,
) -> int:
    outcome_store = ParallelForecastOutcomeStoreV2(db_path)
    resolved = 0
    now = datetime.now(timezone.utc)
    for experiment in load_unresolved_parallel_experiments_v2(db_path=db_path, limit=limit):
        points = history_store.load_range(
            market=experiment.market,
            start=_utc(experiment.forecast_as_of),
            end=now,
            limit=max(5000, int(experiment.horizon_seconds / 60) * 10 + 1000),
        )
        outcome = evaluate_parallel_forecast_experiment_v2(experiment, points)
        if outcome is not None and outcome_store.save(outcome):
            resolved += 1
    return resolved


def run_parallel_forecast_runtime_cycle_v2(
    produced: ProducedTechnicalRuntimeV2,
    *,
    history_store: MarketHistoryStore,
    db_path: str = "pricegauger.db",
    scope_key: str = "global",
) -> ParallelForecastRuntimeSummaryV2:
    attempted, inserted = record_parallel_experiments_v2(
        produced, db_path=db_path, scope_key=scope_key
    )
    resolved = resolve_parallel_outcomes_v2(history_store=history_store, db_path=db_path)
    return ParallelForecastRuntimeSummaryV2(attempted, inserted, resolved)
