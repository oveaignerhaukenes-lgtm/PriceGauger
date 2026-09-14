from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping

import pandas as pd


OVERSEER_STRATEGY_KEY_V1 = "market-state-overseer-v1"
OVERSEER_LABEL_V1 = "Overseer"
FLAT_MODEL_V1 = "FLAT"


@dataclass(frozen=True, slots=True)
class MarketStateV1:
    efficiency: float
    persistence: float
    noise: float
    volatility: float
    volatility_acceleration: float
    impulse: float
    reversal_rate: float

    def vector(self) -> tuple[float, ...]:
        return (
            self.efficiency,
            self.persistence,
            self.noise,
            self.volatility,
            self.volatility_acceleration,
            self.impulse,
            self.reversal_rate,
        )


@dataclass(frozen=True, slots=True)
class OverseerDecisionV1:
    model: str
    confidence: float
    state: MarketStateV1
    reason: str


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def market_state_v1(price: pd.Series, *, short_window: int = 12, long_window: int = 48) -> MarketStateV1:
    clean = pd.to_numeric(price, errors="coerce").dropna()
    if len(clean) < 6:
        return MarketStateV1(0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
    block = clean.iloc[-max(6, int(long_window)):]
    delta = block.diff().dropna()
    abs_delta = delta.abs()
    travel = float(abs_delta.sum())
    net = abs(float(block.iloc[-1]) - float(block.iloc[0]))
    efficiency = 0.0 if travel <= 0.0 else _clamp(net / travel)
    signs = delta[delta != 0.0].map(lambda value: 1 if value > 0.0 else -1)
    reversal_rate = 0.0 if len(signs) < 2 else float((signs != signs.shift(1)).iloc[1:].mean())
    persistence = _clamp(1.0 - reversal_rate)
    noise = _clamp((1.0 - efficiency) * 0.65 + reversal_rate * 0.35)

    returns = block.pct_change().dropna()
    long_vol = float(returns.std(ddof=0)) if len(returns) else 0.0
    short = returns.iloc[-max(3, int(short_window)):]
    short_vol = float(short.std(ddof=0)) if len(short) else 0.0
    baseline = max(long_vol, 1e-12)
    volatility = _clamp(short_vol / (baseline * 2.0))
    volatility_acceleration = _clamp((short_vol / baseline - 0.75) / 1.5)

    recent_abs = abs_delta.iloc[-max(3, int(short_window)):]
    impulse = 0.0 if travel <= 0.0 or recent_abs.empty else _clamp(
        float(recent_abs.max()) / max(float(abs_delta.mean()) * 3.0, 1e-12)
    )
    return MarketStateV1(
        efficiency=efficiency,
        persistence=persistence,
        noise=noise,
        volatility=volatility,
        volatility_acceleration=volatility_acceleration,
        impulse=impulse,
        reversal_rate=_clamp(reversal_rate),
    )


def state_distance_v1(left: MarketStateV1, right: MarketStateV1) -> float:
    weights = (1.35, 1.0, 1.35, 0.8, 1.0, 1.1, 1.0)
    return math.sqrt(sum(w * ((a - b) ** 2) for a, b, w in zip(left.vector(), right.vector(), weights)))


def _entry_threshold(risk: float) -> float:
    # Risk controls how readily FLAT yields to a model, not market direction.
    return 0.72 - (0.34 * _clamp(risk))


def choose_model_v1(
    current: MarketStateV1,
    historical_states: pd.DataFrame,
    future_model_returns: pd.DataFrame,
    *,
    risk: float = 0.5,
    current_model: str = FLAT_MODEL_V1,
    neighbours: int = 80,
    switch_margin: float = 0.08,
) -> OverseerDecisionV1:
    """Select a tool from similar past states; FLAT is a first-class competitor.

    `future_model_returns` must be computed strictly after each historical state. The
    caller is responsible for walk-forward/OOS separation; this function never peeks at
    future rows belonging to the current decision.
    """
    if historical_states.empty or future_model_returns.empty:
        return OverseerDecisionV1(FLAT_MODEL_V1, 0.0, current, "insufficient history")
    required = list(MarketStateV1.__dataclass_fields__)
    if any(name not in historical_states.columns for name in required):
        raise ValueError("historical market-state features are incomplete")
    common = historical_states.index.intersection(future_model_returns.index)
    if len(common) < 12:
        return OverseerDecisionV1(FLAT_MODEL_V1, 0.0, current, "insufficient comparable states")

    distances = []
    for idx, row in historical_states.loc[common, required].iterrows():
        state = MarketStateV1(*(float(row[name]) for name in required))
        distances.append((idx, state_distance_v1(current, state)))
    distances.sort(key=lambda item: item[1])
    selected = distances[: max(12, min(int(neighbours), len(distances)))]
    ids = [idx for idx, _ in selected]
    d = pd.Series({idx: distance for idx, distance in selected}, dtype="float64")
    weights = 1.0 / (0.08 + d)

    scores: dict[str, float] = {FLAT_MODEL_V1: 0.0}
    evidence: dict[str, int] = {FLAT_MODEL_V1: len(ids)}
    for model in future_model_returns.columns:
        values = pd.to_numeric(future_model_returns.loc[ids, model], errors="coerce").dropna()
        if len(values) < 8:
            continue
        w = weights.reindex(values.index).fillna(0.0)
        weighted_mean = float((values * w).sum() / max(float(w.sum()), 1e-12))
        downside = float(values[values < 0.0].abs().mean()) if (values < 0.0).any() else 0.0
        scores[str(model)] = weighted_mean - (0.35 * downside)
        evidence[str(model)] = len(values)

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_model, best_score = ranked[0]
    runner_score = ranked[1][1] if len(ranked) > 1 else 0.0
    scale = max(abs(best_score), abs(runner_score), 0.02)
    confidence = _clamp((best_score - runner_score) / scale)
    threshold = _entry_threshold(risk)

    if best_model == FLAT_MODEL_V1 or best_score <= 0.0 or confidence < threshold:
        return OverseerDecisionV1(
            FLAT_MODEL_V1,
            confidence,
            current,
            f"FLAT wins: best={best_model} score={best_score:.4f} confidence={confidence:.2f} threshold={threshold:.2f}",
        )

    if current_model not in {"", FLAT_MODEL_V1, best_model}:
        incumbent = scores.get(current_model, float("-inf"))
        if incumbent != float("-inf") and best_score < incumbent + abs(incumbent) * switch_margin + 0.002:
            return OverseerDecisionV1(
                current_model,
                confidence,
                current,
                f"hysteresis keeps {current_model}; challenger {best_model} edge too small",
            )

    return OverseerDecisionV1(
        best_model,
        confidence,
        current,
        f"{best_model} best in {evidence.get(best_model, 0)} similar historical states; score={best_score:.4f}",
    )


__all__ = [
    "FLAT_MODEL_V1",
    "MarketStateV1",
    "OVERSEER_LABEL_V1",
    "OVERSEER_STRATEGY_KEY_V1",
    "OverseerDecisionV1",
    "choose_model_v1",
    "market_state_v1",
    "state_distance_v1",
]
