from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


TIMEFRAMES_V1 = (1, 2, 5, 10, 15, 30)


@dataclass(frozen=True, slots=True)
class MacdTimeframeStateV1:
    minutes: int
    spread: float
    previous_spread: float

    @property
    def direction(self) -> int:
        return 1 if self.spread > 0.0 else -1 if self.spread < 0.0 else 0

    @property
    def slope(self) -> float:
        return self.spread - self.previous_spread


@dataclass(frozen=True, slots=True)
class MacdSupervisorDecisionV1:
    target: int
    score: float
    confidence: float
    context_score: float
    change_score: float
    explanation: str


def _normalized_strength(states: Mapping[int, MacdTimeframeStateV1]) -> dict[int, float]:
    scale = max((abs(item.spread) for item in states.values()), default=0.0)
    if scale <= 0.0:
        return {minutes: 0.0 for minutes in TIMEFRAMES_V1}
    return {minutes: max(-1.0, min(1.0, states[minutes].spread / scale)) for minutes in TIMEFRAMES_V1}


def evaluate_macd_supervisor_v1(
    states: Mapping[int, MacdTimeframeStateV1],
    *,
    current_target: int = 0,
    switch_threshold: float = 0.22,
) -> MacdSupervisorDecisionV1:
    """Explainable multi-timeframe MACD supervisor.

    Slow timeframes describe context while fast/middle timeframes detect a change
    propagating through the market. This deliberately is not majority voting: 1m
    noise cannot outvote a strong 15m/30m backdrop by itself.
    """
    missing = [minutes for minutes in TIMEFRAMES_V1 if minutes not in states]
    if missing:
        raise ValueError(f"MACD supervisor missing timeframes: {missing}")

    strength = _normalized_strength(states)
    # Context is intentionally dominated by closed 30m/15m bars.
    context_weights = {30: 0.50, 15: 0.30, 10: 0.15, 5: 0.05}
    context = sum(strength[m] * weight for m, weight in context_weights.items())

    # Change is strongest when a move has propagated from micro into 5m/10m.
    change_weights = {1: 0.08, 2: 0.17, 5: 0.35, 10: 0.30, 15: 0.10}
    directional_change = 0.0
    for minutes, weight in change_weights.items():
        state = states[minutes]
        slope_direction = 1.0 if state.slope > 0.0 else -1.0 if state.slope < 0.0 else 0.0
        directional_change += weight * ((0.65 * strength[minutes]) + (0.35 * slope_direction))

    # When 1m->2m->5m agree and 10m is joining, promote the emerging move before
    # waiting for the old 30m context to cross. Isolated 1m/2m disagreement gets no boost.
    cascade = 0.0
    d1, d2, d5, d10 = (states[m].direction for m in (1, 2, 5, 10))
    if d1 != 0 and d1 == d2 == d5:
        cascade = 0.18 * d1
        if d10 == d1:
            cascade += 0.12 * d1

    score = max(-1.0, min(1.0, (0.58 * context) + (0.42 * directional_change) + cascade))
    threshold = max(0.05, min(0.75, float(switch_threshold)))
    if score > threshold:
        proposed = 1
    elif score < -threshold:
        proposed = -1
    else:
        proposed = current_target if current_target in (-1, 1) else 0

    # A strong slow backdrop requires material multi-timeframe evidence to reverse.
    slow_direction = 1 if context > 0.30 else -1 if context < -0.30 else 0
    if current_target == slow_direction and proposed == -slow_direction and abs(directional_change) < 0.45:
        proposed = current_target

    confidence = min(1.0, abs(score))
    target_word = "LONG" if proposed > 0 else "SHORT" if proposed < 0 else "HOLD"
    context_word = "bullish" if context > 0.10 else "bearish" if context < -0.10 else "mixed"
    change_word = "up" if directional_change > 0.10 else "down" if directional_change < -0.10 else "unclear"
    explanation = (
        f"{target_word}: slow context {context_word} ({context:+.2f}); "
        f"fast/mid propagation {change_word} ({directional_change:+.2f}); "
        f"cascade {cascade:+.2f}; total {score:+.2f}."
    )
    return MacdSupervisorDecisionV1(
        target=proposed,
        score=float(score),
        confidence=float(confidence),
        context_score=float(context),
        change_score=float(directional_change),
        explanation=explanation,
    )


__all__ = [
    "TIMEFRAMES_V1",
    "MacdSupervisorDecisionV1",
    "MacdTimeframeStateV1",
    "evaluate_macd_supervisor_v1",
]
