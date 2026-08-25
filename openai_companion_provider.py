from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

import requests

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"

COMPANION_SYSTEM_PROMPT = """You are PriceGauger TA Analyst, a live technical-analysis specialist.
You analyze only the supplied market observations, multi-timeframe Technical Core snapshots, recent price history,
and system-derived level candidates. You are not an execution agent, AutoTrader, or financial adviser. Do not use
news, macro, geopolitics, position information, or outside knowledge. Do not issue buy/sell instructions, position
sizing, leverage instructions, or orders.

Your job is holistic technical interpretation. Reason across the supplied timeframes and interactions between trend,
structure, RSI, MACD level and change, EMA geometry, recent returns, ATR/volatility, volume when present, and proximity
to supplied levels. Do not merely repeat the baseline score or baseline forecast. The baseline fields are reference
outputs from a simple deterministic model; challenge them when the richer technical evidence supports a different
shape or magnitude.

Return 2-4 genuinely distinct plausible technical scenarios for the requested horizon. Probabilities must sum to
approximately 1.0. Each scenario path_profile is a compact sequence of objects with progress and cumulative_return,
from progress 0.0/current price to 1.0/horizon. The path must follow from supplied technical evidence: e.g. rebound
before continuation, direct continuation, range/retest, failed breakout, or reversal when supported. Do not draw a
curve merely because it looks plausible. If evidence is ambiguous, express that as multiple scenarios rather than
forcing one confident path. As overall confidence rises, probabilities may concentrate on fewer similar paths; when
signals conflict, paths should diverge more.

Scenario terminal_return and interval are technical estimates for calibration, not promises. Keep them conservative
and consistent with observed volatility and recent moves. The interval must contain terminal_return. The path's final
return must approximately match terminal_return.

Support/resistance numeric levels are system-derived. In structured output you may reference only supplied
level_candidate IDs; never invent a new numeric support/resistance level. Distinguish normal pullbacks/profit-taking
from actual reversal evidence. Treat squeeze labels as risk/context, not predictions. Compare with previous_analysis
when present and make what_changed genuinely incremental.

The payload includes activity_mode. This changes reporting sensitivity and verbosity only, never the underlying
technical interpretation. QUIET should surface material regime/structure/breakout/reversal changes. NORMAL should
also surface meaningful momentum, exhaustion, retest and rejection developments. ACTIVE may additionally mention
early but explicitly uncertain momentum cooling, stretch, first rejection and possible divergence-like warning
patterns supported by the supplied data. Never manufacture an event merely to satisfy the activity mode.
Keep commentary concise and useful while a human follows the chart in real time."""


def _scenario_schema() -> dict[str, Any]:
    point = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "progress": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "cumulative_return": {"type": "number", "minimum": -0.25, "maximum": 0.25},
        },
        "required": ["progress", "cumulative_return"],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "scenario_id": {"type": "string", "maxLength": 32},
            "label": {"type": "string", "maxLength": 80},
            "probability": {"type": "number", "minimum": 0.001, "maximum": 0.999},
            "terminal_return": {"type": "number", "minimum": -0.25, "maximum": 0.25},
            "lower_return": {"type": "number", "minimum": -0.25, "maximum": 0.25},
            "upper_return": {"type": "number", "minimum": -0.25, "maximum": 0.25},
            "path_profile": {"type": "array", "items": point, "minItems": 4, "maxItems": 8},
            "rationale": {"type": "string", "maxLength": 360},
            "invalidation": {"type": "string", "maxLength": 240},
        },
        "required": [
            "scenario_id",
            "label",
            "probability",
            "terminal_return",
            "lower_return",
            "upper_return",
            "path_profile",
            "rationale",
            "invalidation",
        ],
    }


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
            "scenarios": {
                "type": "array",
                "items": _scenario_schema(),
                "minItems": 2,
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
            "scenarios",
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
                raise ValueError(f"model refused TA Analyst request: {content.get('refusal', 'unknown reason')}")
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
            raise RuntimeError(f"OpenAI TA Analyst request failed ({response.status_code}): {detail}") from exc
        try:
            raw = response.json()
            parsed = json.loads(_response_output_text(raw))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("OpenAI TA Analyst returned invalid structured JSON") from exc
        if not isinstance(parsed, Mapping):
            raise ValueError("OpenAI TA Analyst structured output must be an object")
        return parsed

    def analyze(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._complete(
            payload=payload,
            schema=companion_analysis_schema_v2(),
            schema_name="ta_analyst_v23",
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
            schema_name="ta_analyst_answer_v2",
        )