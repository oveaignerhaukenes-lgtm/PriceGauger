from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from database import connect
from parallel_forecast_evaluation_v2 import ForecastCandidateV2, ParallelForecastExperimentV2


@dataclass(frozen=True, slots=True)
class ManualMixPreviewV2:
    market: str
    forecast_as_of: str
    horizon_seconds: int
    mix_fraction: float
    technical_return: float
    technical_context_return: float
    preview_return: float
    preview_lower_return: float
    preview_upper_return: float
    direction: str
    experiment_id: str
    outcome_key: str


def _bounded_mix(value: float) -> float:
    result = float(value)
    if not 0.0 <= result <= 1.0:
        raise ValueError("mix_fraction must be between 0 and 1")
    return result


def _lerp(a: float, b: float, fraction: float) -> float:
    return float(a) + (float(b) - float(a)) * fraction


def blend_manual_mix_preview_v2(
    experiment: ParallelForecastExperimentV2,
    *,
    mix_fraction: float,
) -> ManualMixPreviewV2:
    """Linearly preview TECH_ONLY -> fixed TECH_CONTEXT without persistence or learning."""
    fraction = _bounded_mix(mix_fraction)
    technical = experiment.technical
    context = experiment.technical_context
    expected = _lerp(technical.predicted_return, context.predicted_return, fraction)
    lower = _lerp(technical.lower_return, context.lower_return, fraction)
    upper = _lerp(technical.upper_return, context.upper_return, fraction)
    direction = "BULLISH" if expected > 0 else "BEARISH" if expected < 0 else "NEUTRAL"
    return ManualMixPreviewV2(
        market=experiment.market,
        forecast_as_of=experiment.forecast_as_of,
        horizon_seconds=experiment.horizon_seconds,
        mix_fraction=fraction,
        technical_return=technical.predicted_return,
        technical_context_return=context.predicted_return,
        preview_return=expected,
        preview_lower_return=lower,
        preview_upper_return=upper,
        direction=direction,
        experiment_id=experiment.experiment_id,
        outcome_key=experiment.outcome_key,
    )


def _from_record(record: dict) -> ParallelForecastExperimentV2:
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


def load_latest_mix_basis_v2(
    *,
    db_path: str | Path = "pricegauger.db",
    market: str | None = None,
    horizon_seconds: int | None = None,
) -> ParallelForecastExperimentV2 | None:
    clauses: list[str] = []
    params: list[object] = []
    if market is not None:
        clauses.append("market = ?")
        params.append(str(market))
    if horizon_seconds is not None:
        if int(horizon_seconds) <= 0:
            raise ValueError("horizon_seconds must be positive")
        clauses.append("horizon_seconds = ?")
        params.append(int(horizon_seconds))
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with connect(str(db_path)) as db:
        row = db.execute(
            f"""
            SELECT payload_json
            FROM pg_v2_forecast_experiments
            {where}
            ORDER BY forecast_as_of DESC, recorded_at DESC
            LIMIT 1
            """,
            tuple(params),
        ).fetchone()
    if row is None:
        return None
    return _from_record(json.loads(row["payload_json"]))
