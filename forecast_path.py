from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ForecastPathEvidence:
    """Persisted-analysis inputs that may legitimately influence path timing."""

    market_regime: str = ""
    volatility_score: float | None = None


def _bounded(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def technical_direction_from_regime(regime: str) -> float:
    """Recover the signed technical bias encoded by TechnicalStateRuntime."""
    value = str(regime).upper()
    if "SLIGHTLY BULLISH" in value:
        return 0.45
    if "BULLISH" in value:
        return 1.0
    if "SLIGHTLY BEARISH" in value:
        return -0.45
    if "BEARISH" in value:
        return -1.0
    return 0.0


def analysis_path_move(
    progress: float,
    endpoint_pct: float,
    *,
    decision_score: float,
    confidence: float,
    evidence: ForecastPathEvidence,
) -> float:
    """Return a deterministic path point whose geometry is justified by analysis.

    The endpoint remains authoritative. Technical alignment only changes *when*
    the move is expressed inside the horizon: aligned technical state front-loads
    part of the move, while opposing technical state may produce an initial
    counter-move before convergence. No random jitter or named chart pattern is
    introduced.
    """
    p = _bounded(progress)
    endpoint = float(endpoint_pct)
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return endpoint

    confidence = _bounded(confidence)
    volatility = _bounded(0.0 if evidence.volatility_score is None else evidence.volatility_score)
    if endpoint > 0.0:
        thesis_sign = 1.0
    elif endpoint < 0.0:
        thesis_sign = -1.0
    else:
        thesis_sign = 1.0 if float(decision_score) >= 0.0 else -1.0

    technical = technical_direction_from_regime(evidence.market_regime)
    alignment = thesis_sign * technical
    bridge = 4.0 * p * (1.0 - p)  # exactly zero at origin and terminal endpoint
    move = endpoint * p

    if alignment > 0.0:
        frontload = (
            abs(endpoint)
            * 0.18
            * alignment
            * (0.5 + 0.5 * confidence)
            * (1.0 - 0.35 * volatility)
            * bridge
        )
        move += thesis_sign * frontload
    elif alignment < 0.0:
        counter_move = (
            abs(endpoint)
            * (0.12 + 0.24 * volatility)
            * (-alignment)
            * (0.65 + 0.35 * confidence)
            * bridge
        )
        move -= thesis_sign * counter_move

    return move


def transient_path_uncertainty_pct(
    progress: float,
    endpoint_pct: float,
    *,
    confidence: float,
    evidence: ForecastPathEvidence,
) -> float:
    """Volatility-derived intrahorizon uncertainty that vanishes at both ends."""
    p = _bounded(progress)
    if p <= 0.0 or p >= 1.0:
        return 0.0
    volatility = _bounded(0.0 if evidence.volatility_score is None else evidence.volatility_score)
    confidence = _bounded(confidence)
    bridge = 4.0 * p * (1.0 - p)
    scale = max(abs(float(endpoint_pct)), 0.10)
    return scale * (0.06 + 0.28 * volatility) * (1.15 - 0.45 * confidence) * bridge
