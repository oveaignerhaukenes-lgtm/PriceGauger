from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable
from uuid import NAMESPACE_URL, uuid5

from forecast_outcome_evaluation_v2 import (
    ForecastClaimV2,
    direction_hit_v2,
    evaluate_forecast_claim_v2,
    interval_hit_v2,
)
from parallel_forecast_evaluation_v2 import ForecastCandidateV2, ParallelForecastExperimentV2


@dataclass(frozen=True, slots=True)
class CandidateOutcomeScoreV2:
    candidate_kind: str
    predicted_return: float
    realized_return: float
    signed_error: float
    absolute_error: float
    direction_hit: bool
    interval_hit: bool

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ParallelForecastOutcomeV2:
    outcome_key: str
    market: str
    forecast_as_of: str
    horizon_seconds: int
    matured_at: str
    reference_price: float
    realized_terminal_price: float
    realized_return: float
    technical: CandidateOutcomeScoreV2
    technical_context: CandidateOutcomeScoreV2

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


def _claim_for_candidate(
    experiment: ParallelForecastExperimentV2,
    candidate: ForecastCandidateV2,
) -> ForecastClaimV2:
    return ForecastClaimV2(
        forecast_id=uuid5(NAMESPACE_URL, f"pricegauger:{experiment.outcome_key}:{candidate.candidate_kind}"),
        market_id=0,
        as_of=experiment.forecast_as_of,
        horizon_seconds=experiment.horizon_seconds,
        baseline_return=experiment.technical.predicted_return,
        composed_return=candidate.predicted_return,
        lower_return=candidate.lower_return,
        upper_return=candidate.upper_return,
    )


def _score_candidate(
    experiment: ParallelForecastExperimentV2,
    candidate: ForecastCandidateV2,
    points: Iterable[tuple[str, float]],
) -> tuple[CandidateOutcomeScoreV2, object] | None:
    claim = _claim_for_candidate(experiment, candidate)
    outcome = evaluate_forecast_claim_v2(claim, points)
    if outcome is None:
        return None
    direction = direction_hit_v2(claim, outcome)
    interval = interval_hit_v2(claim, outcome)
    return (
        CandidateOutcomeScoreV2(
            candidate_kind=candidate.candidate_kind,
            predicted_return=candidate.predicted_return,
            realized_return=outcome.realized_return,
            signed_error=float(outcome.signed_error),
            absolute_error=float(outcome.absolute_error),
            direction_hit=bool(direction),
            interval_hit=bool(interval),
        ),
        outcome,
    )


def evaluate_parallel_forecast_experiment_v2(
    experiment: ParallelForecastExperimentV2,
    points: Iterable[tuple[str, float]],
) -> ParallelForecastOutcomeV2 | None:
    """Resolve both candidates against one identical realized price path.

    The canonical active-market-time semantics are delegated to
    ``forecast_outcome_evaluation_v2``. Both candidates therefore share exactly
    the same reference price, terminal price, maturity timestamp and realized
    return; only their prediction errors/coverage may differ.
    """
    frozen_points = tuple(points)
    technical_result = _score_candidate(experiment, experiment.technical, frozen_points)
    context_result = _score_candidate(experiment, experiment.technical_context, frozen_points)
    if technical_result is None or context_result is None:
        return None

    technical_score, technical_outcome = technical_result
    context_score, context_outcome = context_result
    shared = (
        technical_outcome.matured_at,
        technical_outcome.reference_price,
        technical_outcome.realized_terminal_price,
        technical_outcome.realized_return,
    )
    other = (
        context_outcome.matured_at,
        context_outcome.reference_price,
        context_outcome.realized_terminal_price,
        context_outcome.realized_return,
    )
    if shared != other:
        raise ValueError("parallel candidates did not resolve to one shared outcome")

    return ParallelForecastOutcomeV2(
        outcome_key=experiment.outcome_key,
        market=experiment.market,
        forecast_as_of=experiment.forecast_as_of,
        horizon_seconds=experiment.horizon_seconds,
        matured_at=technical_outcome.matured_at,
        reference_price=technical_outcome.reference_price,
        realized_terminal_price=technical_outcome.realized_terminal_price,
        realized_return=technical_outcome.realized_return,
        technical=technical_score,
        technical_context=context_score,
    )
