from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

import requests

from market_interpretation import STATE_NAMES

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


def market_interpretation_output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "summary": {"type": "string", "maxLength": 280},
            "state_deltas": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    name: {"type": "number", "minimum": -1.0, "maximum": 1.0}
                    for name in STATE_NAMES
                },
                "required": list(STATE_NAMES),
            },
            "novelty": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "source_quality": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "evidence": {
                "type": "array",
                "items": {"type": "string", "maxLength": 280},
                "maxItems": 5,
            },
            "uncertainties": {
                "type": "array",
                "items": {"type": "string", "maxLength": 280},
                "maxItems": 5,
            },
        },
        "required": [
            "summary",
            "state_deltas",
            "novelty",
            "confidence",
            "source_quality",
            "evidence",
            "uncertainties",
        ],
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
                raise ValueError(f"model refused interpretation: {content.get('refusal', 'unknown reason')}")
    raise ValueError("OpenAI response did not contain output text")


@dataclass(slots=True)
class OpenAIJsonProvider:
    api_key: str
    model_version: str = "gpt-5-mini"
    timeout_seconds: float = 45.0

    def complete_json(self, *, system_prompt: str, user_payload: Mapping[str, Any]) -> Mapping[str, Any]:
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
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": json.dumps(dict(user_payload), ensure_ascii=False, sort_keys=True),
                    },
                ],
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "market_interpretation",
                        "schema": market_interpretation_output_schema(),
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
            raise RuntimeError(f"OpenAI request failed ({response.status_code}): {detail}") from exc
        try:
            raw = response.json()
        except ValueError as exc:
            raise ValueError("OpenAI returned a non-JSON response") from exc
        try:
            parsed = json.loads(_response_output_text(raw))
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("OpenAI returned invalid structured JSON") from exc
        if not isinstance(parsed, Mapping):
            raise ValueError("OpenAI structured output must be a JSON object")
        return parsed
