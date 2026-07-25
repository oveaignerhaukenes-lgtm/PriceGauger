from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Mapping

import requests

from config import openai_api_key, openai_market_model
from event_resolution import CanonicalEvent, EventFacts
from telegram_query_builder import build_search_plan

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
INPUT_TYPES = ("EVENT", "SEARCH_REQUEST", "SCENARIO")
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{2,}")
_STOPWORDS = {
    "after", "against", "amid", "and", "are", "breaking", "from", "into",
    "near", "over", "reported", "reports", "says", "that", "the", "their",
    "this", "with", "will", "would", "could", "market", "markets", "price",
    "prices", "impact", "analysis", "event", "news",
}


@dataclass(frozen=True, slots=True)
class AnalysisInput:
    input_id: str
    input_type: str
    source: str
    raw_text: str
    source_url: str = ""
    published_at: str = ""

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SemanticInterpretation:
    input_type: str
    summary: str
    event_type: str
    target: str
    country: str
    domain: str
    search_keywords: tuple[str, ...]
    affected_assets: tuple[str, ...]
    confidence: float
    uncertainties: tuple[str, ...]
    model_version: str

    @property
    def search(self) -> str:
        return " ".join(self.search_keywords)

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["search_keywords"] = list(self.search_keywords)
        record["affected_assets"] = list(self.affected_assets)
        record["uncertainties"] = list(self.uncertainties)
        record["search"] = self.search
        return record


def compact_search_keywords(
    values: list[str] | tuple[str, ...],
    *,
    event_type: str = "",
    target: str = "",
    country: str = "",
    maximum: int = 6,
) -> tuple[str, ...]:
    """Build a compact search vocabulary; never pass summaries or sentences to GDELT."""
    terms: list[str] = []
    for value in (country, target, event_type, *values):
        for token in _TOKEN_RE.findall(str(value or "")):
            lowered = token.lower()
            if lowered in _STOPWORDS or lowered in terms:
                continue
            terms.append(lowered)
            if len(terms) >= maximum:
                return tuple(terms)
    if len(terms) < 2:
        raise ValueError("Kunne ikke ekstrahere minst to presise GDELT-nøkkelord")
    return tuple(terms)


def _schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "input_type": {"type": "string", "enum": list(INPUT_TYPES)},
            "summary": {"type": "string", "maxLength": 320},
            "event_type": {"type": "string", "maxLength": 80},
            "target": {"type": "string", "maxLength": 100},
            "country": {"type": "string", "maxLength": 80},
            "domain": {"type": "string", "maxLength": 80},
            "search_keywords": {
                "type": "array",
                "description": "Exactly 3-6 concrete entities, locations or actions. No sentences, explanations, market effects or filler words.",
                "items": {
                    "type": "string",
                    "maxLength": 32,
                    "pattern": "^[A-Za-z0-9][A-Za-z0-9 _-]{1,31}$",
                },
                "minItems": 3,
                "maxItems": 6,
            },
            "affected_assets": {
                "type": "array",
                "items": {"type": "string", "enum": ["Brent", "Gold", "Silver", "DXY"]},
                "maxItems": 4,
            },
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "uncertainties": {
                "type": "array",
                "items": {"type": "string", "maxLength": 240},
                "maxItems": 5,
            },
        },
        "required": [
            "input_type", "summary", "event_type", "target", "country", "domain",
            "search_keywords", "affected_assets", "confidence", "uncertainties",
        ],
    }


def _output_text(payload: Mapping[str, Any]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    for item in payload.get("output", ()):
        if not isinstance(item, Mapping) or item.get("type") != "message":
            continue
        for content in item.get("content", ()):
            if isinstance(content, Mapping) and content.get("type") == "output_text":
                return str(content.get("text") or "")
    raise ValueError("OpenAI response did not contain output text")


def _fallback(value: AnalysisInput, requested_type: str) -> SemanticInterpretation:
    plan = build_search_plan(
        message_id=value.input_id,
        message_url=value.source_url,
        text=value.raw_text,
        published_at=value.published_at,
    )
    chosen = requested_type if requested_type in INPUT_TYPES else "EVENT"
    assets: list[str] = []
    text = value.raw_text.lower()
    if any(term in text for term in ("oil", "brent", "refinery", "pipeline", "hormuz", "tanker", "shipping")):
        assets.append("Brent")
    if any(term in text for term in ("gold", "safe haven", "war", "conflict", "uncertainty")):
        assets.append("Gold")
    if any(term in text for term in ("silver", "industrial", "solar")):
        assets.append("Silver")
    if any(term in text for term in ("dollar", "usd", "dxy", "fed", "rates")):
        assets.append("DXY")
    keywords = compact_search_keywords(
        tuple(plan.search.split()),
        event_type=plan.event_type,
        target=plan.target,
        country=plan.country,
    )
    return SemanticInterpretation(
        input_type=chosen,
        summary=value.raw_text[:320],
        event_type=plan.event_type,
        target=plan.target,
        country=plan.country,
        domain=plan.domain,
        search_keywords=keywords,
        affected_assets=tuple(dict.fromkeys(assets)),
        confidence=0.55,
        uncertainties=("Rule-based fallback; free AI semantic interpretation was unavailable.",),
        model_version="semantic-fallback-v2",
    )


def interpret_analysis_input(value: AnalysisInput, *, requested_type: str = "AUTO") -> SemanticInterpretation:
    key = openai_api_key()
    if not key:
        return _fallback(value, requested_type)
    model = openai_market_model()
    system_prompt = (
        "Interpret one user or news input for a market-analysis pipeline. Distinguish a reported "
        "real-world EVENT from a SEARCH_REQUEST and a hypothetical SCENARIO. Never turn a question "
        "or hypothetical into a factual event. search_keywords must contain only 3-6 short concrete "
        "entities, locations or actions suitable for a database lookup. Do not include sentences, "
        "explanations, inferred market effects, instrument names unless central to the reported event, "
        "or generic words such as market, price, impact, conflict or news. Do not invent facts."
    )
    response = requests.post(
        OPENAI_RESPONSES_URL,
        headers={"Authorization": f"Bearer {key.strip()}", "Content-Type": "application/json"},
        json={
            "model": model,
            "store": False,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps({
                    "requested_type": requested_type,
                    "source": value.source,
                    "text": value.raw_text,
                }, ensure_ascii=False)},
            ],
            "text": {"format": {"type": "json_schema", "name": "analysis_input", "schema": _schema(), "strict": True}},
        },
        timeout=45,
    )
    response.raise_for_status()
    payload = json.loads(_output_text(response.json()))
    input_type = str(payload["input_type"]).upper()
    if requested_type in INPUT_TYPES:
        input_type = requested_type
    event_type = str(payload["event_type"]).strip() or "other"
    target = str(payload["target"]).strip() or "unspecified"
    country = str(payload["country"]).strip()
    keywords = compact_search_keywords(
        tuple(str(item).strip() for item in payload["search_keywords"] if str(item).strip()),
        event_type=event_type,
        target=target,
        country=country,
    )
    return SemanticInterpretation(
        input_type=input_type,
        summary=str(payload["summary"]).strip(),
        event_type=event_type,
        target=target,
        country=country,
        domain=str(payload["domain"]).strip(),
        search_keywords=keywords,
        affected_assets=tuple(str(item) for item in payload["affected_assets"]),
        confidence=float(payload["confidence"]),
        uncertainties=tuple(str(item) for item in payload["uncertainties"]),
        model_version=model,
    )


def canonical_event_from_input(value: AnalysisInput, interpretation: SemanticInterpretation) -> CanonicalEvent:
    digest = hashlib.sha1(f"{value.source}|{value.raw_text}".encode("utf-8")).hexdigest()[:18]
    published = value.published_at or datetime.now(timezone.utc).isoformat()
    return CanonicalEvent(
        event_id=f"{value.source.lower()}:{digest}",
        cluster_id=f"cluster:{digest}",
        source_message_id=value.input_id,
        source_url=value.source_url,
        title=value.raw_text,
        event_type=interpretation.event_type,
        target=interpretation.target,
        country=interpretation.country,
        domain=interpretation.domain,
        published_at=published,
        relevance_score=interpretation.confidence,
        facts=EventFacts(),
        model_version=f"semantic:{interpretation.model_version}",
    )
