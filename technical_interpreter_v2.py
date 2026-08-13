from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from technical_core_v2 import TechnicalCoreState


TECHNICAL_INTERPRETER_V2_RECIPE = "technical-interpreter-v2.1"


@dataclass(frozen=True, slots=True)
class TechnicalInterpretation:
    market: str
    as_of: str
    recipe_version: str
    directional_bias: str
    continuation_probability: float
    mean_reversion_probability: float
    breakout_probability: float
    rejection_probability: float
    squeeze_probability: float
    confidence: float
    emphasis: dict[str, float]
    human_summary: str
    source_technical_recipe: str

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


def build_technical_interpreter_payload(state: TechnicalCoreState) -> dict[str, Any]:
    return {
        "market": state.market,
        "as_of": state.as_of,
        "technical_recipe": state.recipe_version,
        "primary_timeframe": state.primary_timeframe,
        "trend_state": state.trend_state,
        "momentum_state": state.momentum_state,
        "volatility_state": state.volatility_state,
        "structure_state": state.structure_state,
        "baseline_score": state.score,
        "baseline_confidence": state.confidence,
        "snapshots": state.snapshots,
    }


def validate_technical_interpretation(state: TechnicalCoreState, record: dict[str, Any], *, recipe_version: str = TECHNICAL_INTERPRETER_V2_RECIPE) -> TechnicalInterpretation:
    directional_bias = str(record.get("directional_bias", "")).upper()
    if directional_bias not in {"BULLISH", "BEARISH", "NEUTRAL"}:
        raise ValueError("directional_bias must be BULLISH, BEARISH or NEUTRAL")

    def probability(name: str) -> float:
        value = float(record[name])
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{name} must be between 0 and 1")
        return value

    emphasis_raw = record.get("emphasis") or {}
    if not isinstance(emphasis_raw, dict):
        raise ValueError("emphasis must be an object")
    emphasis: dict[str, float] = {}
    for key, value in emphasis_raw.items():
        numeric = float(value)
        if not 0.0 <= numeric <= 1.0:
            raise ValueError("emphasis weights must be between 0 and 1")
        emphasis[str(key)] = numeric

    human_summary = str(record.get("human_summary", "")).strip()
    if not human_summary:
        raise ValueError("human_summary is required")
    if len(human_summary) > 600:
        raise ValueError("human_summary must remain concise")

    return TechnicalInterpretation(
        market=state.market,
        as_of=state.as_of,
        recipe_version=recipe_version,
        directional_bias=directional_bias,
        continuation_probability=probability("continuation_probability"),
        mean_reversion_probability=probability("mean_reversion_probability"),
        breakout_probability=probability("breakout_probability"),
        rejection_probability=probability("rejection_probability"),
        squeeze_probability=probability("squeeze_probability"),
        confidence=probability("confidence"),
        emphasis=emphasis,
        human_summary=human_summary,
        source_technical_recipe=state.recipe_version,
    )
