from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

import requests

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"

COMPANION_SYSTEM_PROMPT = """You are PriceGauger Analyst Companion, a live technical-analysis companion.
You analyze the supplied market observations and Technical Core state. You are not an execution agent,
AutoTrader, or financial adviser. Do not issue buy/sell instructions, position sizing, leverage instructions,
or orders. Describe technical conditions, uncertainty, plausible interpretations, levels already supplied by
the system, and what observable developments would change the analysis.

Support/resistance numeric levels are system-derived. In structured output you may reference only supplied
level_candidate IDs; never invent a new numeric level. Distinguish normal pullbacks/profit-taking from actual
reversal evidence. Treat squeeze labels as risk/context, not predictions. Compare with previous_analysis when
present and make what_changed genuinely incremental. Keep commentary concise and useful while a human follows
the chart in real time."""


def companion_analysis_schema_v2() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "directional_context": {"type": "string", "enum": ["BULLISH", "BEARISH", "NEUTRAL", "MIXED"]},
            "breakout_status": {
                "type": "string",
                "enum": ["NONE", "TESTING", "BREAKOUT", "RETEST", "REJECTION", "FAILED_BREAKOUT"],
            },
            "pullback_type": {
                "type": "string",
                "enum": ["NONE", "NORMAL", "PROFIT_TAKING", "MEAN_REVERSION", "REVERSAL_RISK", "UNDETERMINED"],
            },
            "squeeze_risk": {"type": "string", "enum": ["LOW", "MODERATE", "HIGH", "UNDETERMINED"]},
            "watched_support_ids": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 3,
            },
            "watched_resistance_ids": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 3,
            },
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "what_changed": {"type": "string", "maxLength": 360},
            "commentary": {"type": "string", "maxLength": 900},
            "watch_conditions": {
                "type": "array",
                "items": {"type": "string", "maxLength": 240},
                "maxItems": 4,
            },
        },
        "required": [
            "directional_context",
            "breakout_status",
            "pullback_type",
            "squeeze_risk",
            "watched_support_ids",
            "watched_resistance_ids",
            "confidence",
            "what_changed",
            "commentary",
            "watch_conditions",
        ],
    }


def companion_answer_schema_v2() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "answer": {"type": "string", "maxLength": 1200},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        },
        "required": ["answer", "confidence"],
    }


def _response_output_text(payload: Mapping[str, Any]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    for item in payload.get("output", ()):
        if not isinstance(item, Mapping) or item.get("type") != "message":
            continue
        for content in item.get("content", ()):
            if not isinstance(content, Mapping):
                continue
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                return str(content["text"])
            if content.get("type") == "refusal":
                raise ValueError(f"model refused Companion request: {content.get('refusal', 'unknown reason')}")
    raise ValueError("OpenAI response did not contain output text")


@dataclass(slots=True)
class OpenAICompanionProviderV2:
    api_key: str
    model_version: str = "gpt-5-mini"
    timeout_seconds: float = 45.0

    def _complete(self, *, payload: Mapping[str, Any], schema: Mapping[str, Any], schema_name: str) -> Mapping[str, Any]:
        if not self.api_key.strip():
            raise ValueError("OPENAI_API_KEY is not configured")
        response = requests.post(
            OPENAI_RESPONSES_URL,
            headers={
                "Authorization": f"Bearer {self.api_key.strip()}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model_version,
                "store": False,
                "input": [
                    {"role": "system", "content": COMPANION_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": json.dumps(dict(payload), ensure_ascii=False, sort_keys=True),
                    },
                ],
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": schema_name,
                        "schema": dict(schema),
                        "strict": True,
                    }
                },
            },
            timeout=self.timeout_seconds,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            detail = response.text[:500].replace(self.api_key, "[redacted]")
            raise RuntimeError(f"OpenAI Companion request failed ({response.status_code}): {detail}") from exc
        try:
            raw = response.json()
            parsed = json.loads(_response_output_text(raw))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("OpenAI Companion returned invalid structured JSON") from exc
        if not isinstance(parsed, Mapping):
            raise ValueError("OpenAI Companion structured output must be an object")
        return parsed

    def analyze(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._complete(
            payload=payload,
            schema=companion_analysis_schema_v2(),
            schema_name="analyst_companion_v2",
        )

    def answer(self, payload: Mapping[str, Any], question: str) -> Mapping[str, Any]:
        request = dict(payload)
        request["question"] = str(question).strip()
        request["instruction"] = (
            "Answer the user's technical-analysis question from supplied observations only. "
            "Do not provide trade instructions or position sizing."
        )
        return self._complete(
            payload=request,
            schema=companion_answer_schema_v2(),
            schema_name="analyst_companion_answer_v2",
        )
