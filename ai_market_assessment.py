from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

import requests

from config import openai_api_key, openai_market_model


ASSESSMENT_VERSION = "ai-market-assessment-v1"
_RESPONSES_URL = "https://api.openai.com/v1/responses"


@dataclass(frozen=True, slots=True)
class AIMarketAssessment:
    instrument: str
    direction: str
    probability_up: float
    probability_down: float
    expected_move_low_pct: float
    expected_move_high_pct: float
    primary_horizon: str
    confidence: float
    causal_thesis: str
    already_priced_assessment: str
    historical_support: str
    technical_confirmation: str
    invalidation_conditions: tuple[str, ...]
    key_uncertainties: tuple[str, ...]
    evidence: tuple[str, ...]
    model: str
    assessment_version: str = ASSESSMENT_VERSION

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


def _response_text(payload: dict[str, Any]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    parts: list[str] = []
    for item in payload.get("output") or []:
        for content in item.get("content") or []:
            if content.get("type") == "output_text" and content.get("text"):
                parts.append(str(content["text"]))
    if not parts:
        raise ValueError("OpenAI response contained no output text")
    return "\n".join(parts)


def build_prompt(
    *,
    instrument: str,
    event: dict[str, Any],
    historical: dict[str, Any] | None,
    semantic_analogues: list[dict[str, Any]],
    technical: dict[str, Any] | None,
) -> str:
    return f"""You are the causal market-analysis engine in PriceGauger.

Assess the likely market response to the current event. Do not mechanically copy the historical direction. Historical analogues are supporting evidence only. Prioritize causal interpretation, surprise versus expectations, what appears already priced, current technical confirmation, and explicit uncertainty.

Return a testable forecast for {instrument}. Probabilities must sum approximately to 1. The expected move interval must be expressed as percentage return from the current reference price over the primary horizon. Use direction MIXED when evidence does not support a directional edge. Do not invent missing market data; state its absence in technical_confirmation or key_uncertainties.

CURRENT EVENT
{json.dumps(event, ensure_ascii=False, indent=2, default=str)}

SEMANTICALLY RANKED HISTORICAL ANALOGUES
{json.dumps(semantic_analogues[:8], ensure_ascii=False, indent=2, default=str)}

HISTORICAL CALIBRATION OUTPUT
{json.dumps(historical, ensure_ascii=False, indent=2, default=str)}

CURRENT TECHNICAL OUTPUT
{json.dumps(technical, ensure_ascii=False, indent=2, default=str)}
"""


def assess_market(
    *,
    instrument: str,
    event: dict[str, Any],
    historical: dict[str, Any] | None,
    semantic_analogues: list[dict[str, Any]],
    technical: dict[str, Any] | None,
    api_key: str | None = None,
    model: str | None = None,
    timeout: int = 60,
    session: Any = requests,
) -> AIMarketAssessment:
    active_key = (api_key if api_key is not None else openai_api_key()).strip()
    active_model = (model if model is not None else openai_market_model()).strip()
    if not active_key:
        raise ValueError("OPENAI_API_KEY is required for AI market assessment")
    if not active_model:
        raise ValueError("OpenAI model is required for AI market assessment")

    schema = {
        "type": "object",
        "properties": {
            "direction": {"type": "string", "enum": ["UP", "DOWN", "MIXED"]},
            "probability_up": {"type": "number", "minimum": 0, "maximum": 1},
            "probability_down": {"type": "number", "minimum": 0, "maximum": 1},
            "expected_move_low_pct": {"type": "number"},
            "expected_move_high_pct": {"type": "number"},
            "primary_horizon": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "causal_thesis": {"type": "string"},
            "already_priced_assessment": {"type": "string"},
            "historical_support": {"type": "string"},
            "technical_confirmation": {"type": "string"},
            "invalidation_conditions": {"type": "array", "items": {"type": "string"}},
            "key_uncertainties": {"type": "array", "items": {"type": "string"}},
            "evidence": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "direction", "probability_up", "probability_down", "expected_move_low_pct",
            "expected_move_high_pct", "primary_horizon", "confidence", "causal_thesis",
            "already_priced_assessment", "historical_support", "technical_confirmation",
            "invalidation_conditions", "key_uncertainties", "evidence"
        ],
        "additionalProperties": False,
    }
    response = session.post(
        _RESPONSES_URL,
        timeout=timeout,
        headers={"Authorization": f"Bearer {active_key}", "Content-Type": "application/json"},
        json={
            "model": active_model,
            "input": build_prompt(
                instrument=instrument,
                event=event,
                historical=historical,
                semantic_analogues=semantic_analogues,
                technical=technical,
            ),
            "text": {"format": {"type": "json_schema", "name": "ai_market_assessment", "strict": True, "schema": schema}},
        },
    )
    response.raise_for_status()
    parsed = json.loads(_response_text(response.json()))
    low = float(parsed["expected_move_low_pct"])
    high = float(parsed["expected_move_high_pct"])
    if low > high:
        low, high = high, low
    return AIMarketAssessment(
        instrument=instrument,
        direction=str(parsed["direction"]),
        probability_up=float(parsed["probability_up"]),
        probability_down=float(parsed["probability_down"]),
        expected_move_low_pct=low,
        expected_move_high_pct=high,
        primary_horizon=str(parsed["primary_horizon"]),
        confidence=float(parsed["confidence"]),
        causal_thesis=str(parsed["causal_thesis"]),
        already_priced_assessment=str(parsed["already_priced_assessment"]),
        historical_support=str(parsed["historical_support"]),
        technical_confirmation=str(parsed["technical_confirmation"]),
        invalidation_conditions=tuple(str(x) for x in parsed["invalidation_conditions"]),
        key_uncertainties=tuple(str(x) for x in parsed["key_uncertainties"]),
        evidence=tuple(str(x) for x in parsed["evidence"]),
        model=active_model,
    )
