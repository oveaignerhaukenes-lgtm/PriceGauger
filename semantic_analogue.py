from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

import requests

from config import openai_api_key, openai_market_model
from gdelt_ingestion import GdeltCandidateRecord
from telegram_query_builder import TelegramSearchPlan

ASSESSMENT_VERSION = "semantic-analogue-v1"
_RESPONSES_URL = "https://api.openai.com/v1/responses"


@dataclass(frozen=True, slots=True)
class AnalogueAssessment:
    source_message_id: str
    candidate_event_id: str
    event_similarity: float
    market_similarity: float
    explanation: str
    model: str
    assessment_version: str
    raw: dict[str, Any]


class AnalogueAssessor(Protocol):
    def assess(
        self,
        source: TelegramSearchPlan,
        candidate: GdeltCandidateRecord,
    ) -> AnalogueAssessment: ...


def _score(value: Any, field_name: str) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a number") from exc
    if not 0.0 <= score <= 1.0:
        raise ValueError(f"{field_name} must be between 0 and 1")
    return score


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


def build_semantic_comparison_prompt(
    source: TelegramSearchPlan,
    candidate: GdeltCandidateRecord,
) -> str:
    """Give the model a clear goal while leaving semantic interpretation open."""
    return f"""Compare a new market-relevant news event with a historical candidate.

Use any semantic, contextual, causal, geopolitical or market-reaction patterns you consider relevant. Do not rely only on shared words. Distinguish between:
1. event_similarity: how similar the events themselves are.
2. market_similarity: how similar they are as potential causes of a market reaction.

Return both scores from 0 to 1 and a concise free-form explanation of the most important similarities and differences.

NEW EVENT
Published: {source.published_at}
Text: {source.message_text}
Initial extraction: event_type={source.event_type}; target={source.target}; country={source.country}

HISTORICAL CANDIDATE
Published: {candidate.published_at or candidate.event_date}
Title: {candidate.title}
Summary: {candidate.summary}
Source country: {candidate.country}
"""


class OpenAIAnalogueAssessor:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        timeout: int = 45,
        session: Any = requests,
    ) -> None:
        self.api_key = (api_key if api_key is not None else openai_api_key()).strip()
        self.model = (model if model is not None else openai_market_model()).strip()
        self.timeout = timeout
        self.session = session
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is required for semantic analogue assessment")
        if not self.model:
            raise ValueError("OpenAI model is required for semantic analogue assessment")

    def assess(
        self,
        source: TelegramSearchPlan,
        candidate: GdeltCandidateRecord,
    ) -> AnalogueAssessment:
        response = self.session.post(
            _RESPONSES_URL,
            timeout=self.timeout,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "input": build_semantic_comparison_prompt(source, candidate),
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "analogue_assessment",
                        "strict": True,
                        "schema": {
                            "type": "object",
                            "properties": {
                                "event_similarity": {"type": "number", "minimum": 0, "maximum": 1},
                                "market_similarity": {"type": "number", "minimum": 0, "maximum": 1},
                                "explanation": {"type": "string"},
                            },
                            "required": ["event_similarity", "market_similarity", "explanation"],
                            "additionalProperties": False,
                        },
                    }
                },
            },
        )
        response.raise_for_status()
        raw_response = response.json()
        parsed = json.loads(_response_text(raw_response))
        explanation = str(parsed.get("explanation") or "").strip()
        if not explanation:
            raise ValueError("analogue assessment explanation is required")

        return AnalogueAssessment(
            source_message_id=source.message_id,
            candidate_event_id=candidate.event_id,
            event_similarity=_score(parsed.get("event_similarity"), "event_similarity"),
            market_similarity=_score(parsed.get("market_similarity"), "market_similarity"),
            explanation=explanation,
            model=self.model,
            assessment_version=ASSESSMENT_VERSION,
            raw={"model_output": parsed, "response": raw_response},
        )
