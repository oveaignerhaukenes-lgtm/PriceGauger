from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


OVERSEER_PERFORMANCE_STRATEGY_KEY_V1 = "overseer-performance-v1"
OVERSEER_PERFORMANCE_LABEL_V1 = "Overseer"
FLAT_MODEL_V1 = "FLAT"


@dataclass(frozen=True, slots=True)
class ModelPerformanceV1:
    model: str
    recent_return_pct: float
    drawdown_pct: float
    positive_share: float
    stability: float


@dataclass(frozen=True, slots=True)
class PerformanceOverseerDecisionV1:
    model: str
    score: float
    incumbent_score: float
    reason: str


def performance_score_v1(item: ModelPerformanceV1) -> float:
    """Score recent realised simulator behaviour; no regime prediction or look-ahead."""
    return (
        float(item.recent_return_pct)
        - 0.70 * abs(min(0.0, float(item.drawdown_pct)))
        + 0.18 * (float(item.positive_share) - 0.5)
        + 0.12 * (float(item.stability) - 0.5)
    )


def choose_performance_model_v1(
    models: Sequence[ModelPerformanceV1],
    *,
    incumbent: str = FLAT_MODEL_V1,
    challenger_margin: float = 0.10,
    minimum_edge: float = 0.02,
) -> PerformanceOverseerDecisionV1:
    """Choose the currently working expert with hysteresis; FLAT is always available.

    Persistence is intentionally handled by the caller: a challenger must remain the
    winner for repeated observations before the caller promotes it. This pure function
    supplies the stable score/margin decision used by shadow replay and, later, live.
    """
    scores: Mapping[str, float] = {item.model: performance_score_v1(item) for item in models}
    if not scores:
        return PerformanceOverseerDecisionV1(FLAT_MODEL_V1, 0.0, 0.0, "no model evidence")
    best_model, best_score = max(scores.items(), key=lambda pair: pair[1])
    incumbent_score = 0.0 if incumbent == FLAT_MODEL_V1 else float(scores.get(incumbent, 0.0))
    if best_score < float(minimum_edge):
        return PerformanceOverseerDecisionV1(FLAT_MODEL_V1, 0.0, incumbent_score, "no model clears FLAT edge")
    if incumbent not in {"", FLAT_MODEL_V1, best_model} and best_score < incumbent_score + float(challenger_margin):
        return PerformanceOverseerDecisionV1(incumbent, incumbent_score, incumbent_score, "hysteresis keeps incumbent")
    return PerformanceOverseerDecisionV1(best_model, best_score, incumbent_score, f"{best_model} leads recent simulator score")


__all__ = [
    "FLAT_MODEL_V1",
    "ModelPerformanceV1",
    "OVERSEER_PERFORMANCE_LABEL_V1",
    "OVERSEER_PERFORMANCE_STRATEGY_KEY_V1",
    "PerformanceOverseerDecisionV1",
    "choose_performance_model_v1",
    "performance_score_v1",
]
