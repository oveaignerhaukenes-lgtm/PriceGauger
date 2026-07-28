from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import requests

from config import openai_api_key, openai_market_model
from telegram_query_builder import TelegramSearchPlan

_RESPONSES_URL = "https://api.openai.com/v1/responses"
INTERPRETATION_VERSION = "telegram-market-search-v1"


def _response_text(payload: dict[str, Any]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct

    parts: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if isinstance(content, dict) and content.get("type") == "output_text" and content.get("text"):
                parts.append(str(content["text"]))
    if not parts:
        raise ValueError("OpenAI response contained no output text")
    return "\n".join(parts)


def build_interpretation_prompt(plan: TelegramSearchPlan) -> str:
    return f"""Interpret a Telegram news post for historical market-analogue retrieval.

Goal: produce a compact, realistic search basis for finding genuinely comparable historical events. Focus on causal event structure, not shared wording.

Identify:
- the principal action/event type
- principal actor, target and country/location
- the causal market channel
- 3 to 6 concise English search concepts likely to retrieve historical analogues

Search concepts must be concrete and reusable across time. Do not write SQL, operators, dates, URLs, prose sentences, or speculative facts. Do not merely copy the entire post. Prefer concepts such as actor/action/target/location or market mechanism. Omit uncertain details rather than inventing them.

POST
Published: {plan.published_at}
Text: {plan.message_text}

RULE-BASED FALLBACK EXTRACTION
Event type: {plan.event_type}
Target: {plan.target}
Country: {plan.country}
Current search: {plan.search}
"""


def _clean_terms(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise ValueError("search_terms must be a list")
    terms: list[str] = []
    for raw in value:
        term = " ".join(str(raw or "").strip().split())
        if not term or len(term) > 64 or term.lower() in {item.lower() for item in terms}:
            continue
        terms.append(term)
    if not 3 <= len(terms) <= 6:
        raise ValueError("search_terms must contain 3 to 6 distinct terms")
    return terms


def _confidence(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("confidence must be numeric") from exc
    if not 0.0 <= result <= 1.0:
        raise ValueError("confidence must be between 0 and 1")
    return result


class OpenAITelegramInterpreter:
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
            raise ValueError("OPENAI_API_KEY is required for Telegram interpretation")
        if not self.model:
            raise ValueError("OpenAI model is required for Telegram interpretation")

    def interpret(self, plan: TelegramSearchPlan) -> TelegramSearchPlan:
        response = self.session.post(
            _RESPONSES_URL,
            timeout=self.timeout,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "input": build_interpretation_prompt(plan),
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "telegram_market_interpretation",
                        "strict": True,
                        "schema": {
                            "type": "object",
                            "properties": {
                                "event_type": {"type": "string"},
                                "actor": {"type": "string"},
                                "target": {"type": "string"},
                                "country": {"type": "string"},
                                "market_channel": {"type": "string"},
                                "search_terms": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "minItems": 3,
                                    "maxItems": 6,
                                },
                                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            },
                            "required": [
                                "event_type",
                                "actor",
                                "target",
                                "country",
                                "market_channel",
                                "search_terms",
                                "confidence",
                            ],
                            "additionalProperties": False,
                        },
                    }
                },
            },
        )
        response.raise_for_status()
        payload = response.json()
        parsed = json.loads(_response_text(payload))
        terms = _clean_terms(parsed.get("search_terms"))
        confidence = _confidence(parsed.get("confidence"))

        event_type = str(parsed.get("event_type") or "").strip() or plan.event_type
        target = str(parsed.get("target") or "").strip() or plan.target
        country = str(parsed.get("country") or "").strip() or plan.country
        actor = str(parsed.get("actor") or "").strip()
        market_channel = str(parsed.get("market_channel") or "").strip()

        return replace(
            plan,
            event_type=event_type,
            target=target,
            country=country,
            search=" ".join(terms),
            signal_score=max(plan.signal_score, 3),
            interpretation_source="openai",
            interpretation_model=self.model,
            interpretation_version=INTERPRETATION_VERSION,
            interpretation_confidence=confidence,
            actor=actor,
            market_channel=market_channel,
            search_terms=tuple(terms),
        )


def interpret_search_plan(plan: TelegramSearchPlan) -> TelegramSearchPlan:
    """Use AI when configured; otherwise preserve the deterministic plan exactly."""
    if not openai_api_key().strip():
        return plan
    try:
        return OpenAITelegramInterpreter().interpret(plan)
    except Exception:
        return plan
