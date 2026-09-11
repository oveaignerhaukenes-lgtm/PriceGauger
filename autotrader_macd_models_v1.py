from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


LONG = "LONG"
SHORT = "SHORT"
FLAT = "FLAT"
DIRECTIONS = {LONG, SHORT, FLAT}

MODEL_MACD2 = "MACD2"
MODEL_MACD2_10 = "MACD2-10"
MODEL_MACD2_S = "MACD2-S"
MODEL_MACD_A = "MACD-A"


@dataclass(frozen=True, slots=True)
class WeightedModelDecisionV1:
    target: str
    score: float
    threshold: float
    components: tuple[tuple[str, float, float], ...]


def _sign_direction(value: float) -> str:
    if float(value) > 0.0:
        return LONG
    if float(value) < 0.0:
        return SHORT
    return FLAT


def macd2_target_v1(spread_2m: float, *, current: str) -> str:
    """Binary 2m MACD target. Zero spread keeps the current target."""
    target = _sign_direction(float(spread_2m))
    return str(current) if target == FLAT else target


def macd2_10_target_v1(spread_2m: float, spread_10m: float, *, current: str) -> str:
    """2m chooses direction; 10m is only a regime filter.

    An opposite 10m regime cannot create a trade. It merely blocks the new 2m flip
    and keeps the current target until the two horizons agree.
    """
    fast = _sign_direction(float(spread_2m))
    slow = _sign_direction(float(spread_10m))
    if fast == FLAT:
        return str(current)
    if slow == fast:
        return fast
    return str(current)


def stochastic_direction_score_v1(
    *,
    previous_k: float,
    previous_d: float,
    current_k: float,
    current_d: float,
) -> float:
    """Return weak stochastic directional evidence in [-1, +1].

    K/D direction is primary; K slope breaks ties. Overbought/oversold levels do not
    veto a MACD signal because stochastic is deliberately only a timing modifier.
    """
    kd_now = float(current_k) - float(current_d)
    kd_prev = float(previous_k) - float(previous_d)
    if kd_now > 0.0 and kd_prev <= 0.0:
        return 1.0
    if kd_now < 0.0 and kd_prev >= 0.0:
        return -1.0
    if kd_now > 0.0:
        return 0.6
    if kd_now < 0.0:
        return -0.6
    slope = float(current_k) - float(previous_k)
    if slope > 0.0:
        return 0.3
    if slope < 0.0:
        return -0.3
    return 0.0


def macd2_stochastic_score_v1(
    *,
    spread_2m: float,
    stochastic_score: float,
    stochastic_weight: float = 0.20,
) -> float:
    """Blend MACD with a bounded 10-20% stochastic timing modifier.

    MACD always owns direction. Stochastic can raise or lower execution confidence,
    but cannot reverse the sign by itself.
    """
    weight = min(0.20, max(0.0, float(stochastic_weight)))
    base_direction = _sign_direction(float(spread_2m))
    if base_direction == FLAT:
        return 0.0
    base = 1.0 if base_direction == LONG else -1.0
    modifier = max(-1.0, min(1.0, float(stochastic_score)))
    return ((1.0 - weight) * base) + (weight * modifier)


def macd2_stochastic_target_v1(
    *,
    spread_2m: float,
    stochastic_score: float,
    current: str,
    stochastic_weight: float = 0.20,
    execute_threshold: float = 0.65,
) -> str:
    """Use stochastic for a brief timing nudge, never as a standing veto.

    With the 20% cap, only a fresh fully-opposite K/D cross can defer the MACD2 flip.
    Persistent opposite K/D direction scores +/-0.6 and therefore cannot keep blocking
    the primary MACD signal on subsequent samples.
    """
    score = macd2_stochastic_score_v1(
        spread_2m=spread_2m,
        stochastic_score=stochastic_score,
        stochastic_weight=stochastic_weight,
    )
    # A caller cannot raise this into a de-facto stochastic veto. MACD remains >=80%
    # of the decision and persistent opposite stochastic direction must still execute.
    threshold = max(0.0, min(0.65, float(execute_threshold)))
    if score >= threshold:
        return LONG
    if score <= -threshold:
        return SHORT
    return str(current)


def adaptive_timeframe_v1(*, micro_edge: float, noise: float) -> int:
    """Choose 1m/2m/5m from externally measured regime evidence.

    micro_edge describes whether fast reversals have recently captured real moves;
    noise describes rapid flips that failed to travel. Inputs are normalized 0..1.
    """
    edge = max(0.0, min(1.0, float(micro_edge)))
    chop = max(0.0, min(1.0, float(noise)))
    if edge >= 0.60 and edge > chop:
        return 1
    if chop >= 0.70 and chop > edge:
        return 5
    return 2


def weighted_model_target_v1(
    scores: Mapping[str, float],
    weights: Mapping[str, float],
    *,
    current: str,
    threshold: float = 0.10,
) -> WeightedModelDecisionV1:
    """Combine model opinions into one target; never split broker exposure.

    Each component score is clipped to [-1,+1]. Positive means LONG, negative SHORT.
    Weights are normalized across positive configured weights. A disagreement band
    keeps the current target rather than creating churn.
    """
    if str(current) not in DIRECTIONS:
        raise ValueError("invalid current direction")
    active: list[tuple[str, float, float]] = []
    total_weight = 0.0
    for name, raw_weight in weights.items():
        weight = max(0.0, float(raw_weight))
        if weight <= 0.0 or name not in scores:
            continue
        score = max(-1.0, min(1.0, float(scores[name])))
        active.append((str(name), score, weight))
        total_weight += weight
    if total_weight <= 0.0:
        raise ValueError("hybrid model needs at least one positive weight")
    normalized = tuple((name, score, weight / total_weight) for name, score, weight in active)
    aggregate = sum(score * weight for _, score, weight in normalized)
    band = max(0.0, min(1.0, float(threshold)))
    if aggregate > band:
        target = LONG
    elif aggregate < -band:
        target = SHORT
    else:
        target = str(current)
    return WeightedModelDecisionV1(
        target=target,
        score=float(aggregate),
        threshold=band,
        components=normalized,
    )


__all__ = [
    "FLAT",
    "LONG",
    "SHORT",
    "MODEL_MACD2",
    "MODEL_MACD2_10",
    "MODEL_MACD2_S",
    "MODEL_MACD_A",
    "WeightedModelDecisionV1",
    "adaptive_timeframe_v1",
    "macd2_10_target_v1",
    "macd2_stochastic_score_v1",
    "macd2_stochastic_target_v1",
    "macd2_target_v1",
    "stochastic_direction_score_v1",
    "weighted_model_target_v1",
]
