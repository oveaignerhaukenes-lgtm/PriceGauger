from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any

from context_snapshot_v2 import ContextSnapshotV2
from holistic_composer_v1 import compose_holistic_forecast_v1
from technical_core_v2 import TechnicalBaselineForecast

TECH_ONLY = "TECH_ONLY"
TECH_CONTEXT = "TECH_CONTEXT"
PARALLEL_EVALUATION_VERSION = "parallel-evaluation-v2.0"


@dataclass(frozen=True, slots=True)
class ForecastCandidateV2:
    candidate_kind: str
    predicted_return: float
    lower_return: float
    upper_return: float
    direction: str
    recipe_version: str
    source_fingerprint: str

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ParallelForecastExperimentV2:
    experiment_id: str
    outcome_key: str
    market: str
    forecast_as_of: str
    horizon_seconds: int
    evaluation_version: str
    technical: ForecastCandidateV2
    technical_context: ForecastCandidateV2
    context_snapshot_id: str
    context_fingerprint: str

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


def _stable_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def outcome_key_v2(*, market: str, forecast_as_of: str, horizon_seconds: int) -> str:
    if int(horizon_seconds) <= 0:
        raise ValueError("horizon_seconds must be positive")
    return _stable_hash({
        "market": str(market).strip().casefold(),
        "forecast_as_of": str(forecast_as_of),
        "horizon_seconds": int(horizon_seconds),
    })


def build_parallel_forecast_experiment_v2(
    *,
    technical: TechnicalBaselineForecast,
    context: ContextSnapshotV2,
) -> ParallelForecastExperimentV2:
    holistic = compose_holistic_forecast_v1(technical=technical, context=context)
    outcome_key = outcome_key_v2(
        market=technical.market,
        forecast_as_of=technical.as_of,
        horizon_seconds=technical.horizon_seconds,
    )
    technical_candidate = ForecastCandidateV2(
        candidate_kind=TECH_ONLY,
        predicted_return=technical.expected_return,
        lower_return=technical.lower_return,
        upper_return=technical.upper_return,
        direction=technical.direction,
        recipe_version=technical.recipe_version,
        source_fingerprint=_stable_hash(technical.to_record()),
    )
    holistic_candidate = ForecastCandidateV2(
        candidate_kind=TECH_CONTEXT,
        predicted_return=holistic.composed_return,
        lower_return=holistic.lower_return,
        upper_return=holistic.upper_return,
        direction=holistic.direction,
        recipe_version=holistic.recipe_version,
        source_fingerprint=holistic.fingerprint,
    )
    identity_payload = {
        "outcome_key": outcome_key,
        "technical": technical_candidate.to_record(),
        "technical_context": holistic_candidate.to_record(),
        "context_snapshot_id": context.snapshot_id,
        "context_fingerprint": context.state_fingerprint,
        "evaluation_version": PARALLEL_EVALUATION_VERSION,
    }
    return ParallelForecastExperimentV2(
        experiment_id=_stable_hash(identity_payload),
        outcome_key=outcome_key,
        market=technical.market,
        forecast_as_of=technical.as_of,
        horizon_seconds=technical.horizon_seconds,
        evaluation_version=PARALLEL_EVALUATION_VERSION,
        technical=technical_candidate,
        technical_context=holistic_candidate,
        context_snapshot_id=context.snapshot_id,
        context_fingerprint=context.state_fingerprint,
    )
