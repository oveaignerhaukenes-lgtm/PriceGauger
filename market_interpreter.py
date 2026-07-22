from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from event_resolution import CanonicalEvent
from market_interpretation import MarketInterpretation, STATE_NAMES

PROMPT_VERSION = "interpreter-v1"


class JsonModelProvider(Protocol):
    model_version: str

    def complete_json(self, *, system_prompt: str, user_payload: Mapping[str, Any]) -> Mapping[str, Any]: ...


def build_interpreter_prompt() -> str:
    return (
        "Interpret one geopolitical market observation. Return JSON only. "
        "Estimate incremental changes, not absolute market levels. "
        "Use exactly these state keys: " + ", ".join(STATE_NAMES) + ". "
        "Every delta must be between -1 and 1. Base evidence only on supplied text. "
        "Do not recommend a trade."
    )


@dataclass(slots=True)
class StructuredMarketInterpreter:
    provider: JsonModelProvider

    def interpret(self, event: CanonicalEvent, *, update_type: str = "NEW_EVENT") -> MarketInterpretation:
        payload = self.provider.complete_json(
            system_prompt=build_interpreter_prompt(),
            user_payload={
                "event_id": event.event_id,
                "cluster_id": event.cluster_id,
                "published_at": event.published_at,
                "text": event.title,
                "event_type": event.event_type,
                "target": event.target,
                "country": event.country,
                "update_type": update_type,
            },
        )
        merged = dict(payload)
        merged.update(
            {
                "event_id": event.event_id,
                "cluster_id": event.cluster_id,
                "published_at": event.published_at,
                "update_type": update_type,
                "model_version": self.provider.model_version,
                "prompt_version": PROMPT_VERSION,
            }
        )
        return MarketInterpretation.from_mapping(merged)


@dataclass(slots=True)
class MockMarketInterpreter:
    """Deterministic semantic stand-in used before a model API is configured."""

    model_version: str = "mock-interpreter-v1"

    def interpret(self, event: CanonicalEvent, *, update_type: str = "NEW_EVENT") -> MarketInterpretation:
        text = event.title.lower()
        deltas = {name: 0.0 for name in STATE_NAMES}

        if event.event_type == "attack" or any(term in text for term in ("attack", "strike", "missile", "drone", "explosion")):
            deltas["conflict_pressure"] += 0.28
            deltas["safe_haven_pressure"] += 0.16
        if event.target == "energy_infrastructure" or any(term in text for term in ("refinery", "pipeline", "oilfield", "oil field", "terminal", "lng")):
            deltas["energy_supply_risk"] += 0.42
            deltas["conflict_pressure"] += 0.08
        if event.target == "shipping" or any(term in text for term in ("hormuz", "tanker", "vessel", "ship", "port", "strait")):
            deltas["shipping_risk"] += 0.40
            deltas["energy_supply_risk"] += 0.18
        if event.target == "diplomatic facility" or any(term in text for term in ("embassy", "consulate", "diplomatic mission")):
            deltas["conflict_pressure"] += 0.18
            deltas["safe_haven_pressure"] += 0.10
        if any(term in text for term in ("ceasefire", "truce", "agreement", "de-escalation", "deescalation")):
            deltas["conflict_pressure"] -= 0.34
            deltas["safe_haven_pressure"] -= 0.18
            deltas["energy_supply_risk"] -= 0.12
            deltas["shipping_risk"] -= 0.12

        confidence = 0.82 if any(term in text for term in ("confirmed", "officially", "verified")) else 0.68
        factor = {
            "NEW_EVENT": 1.0,
            "ESCALATION": 1.0,
            "UPDATE": 0.65,
            "CONFIRMATION": 0.20,
            "DEESCALATION": 1.0,
            "CORRECTION": -1.0,
            "CONTEXT": 0.0,
            "DUPLICATE": 0.0,
        }.get(update_type, 1.0)
        deltas = {name: max(-1.0, min(1.0, value * factor)) for name, value in deltas.items()}
        novelty = {
            "NEW_EVENT": 0.85,
            "ESCALATION": 0.80,
            "UPDATE": 0.45,
            "CONFIRMATION": 0.25,
            "DEESCALATION": 0.80,
            "CORRECTION": 0.90,
            "CONTEXT": 0.05,
            "DUPLICATE": 0.0,
        }.get(update_type, 0.5)

        return MarketInterpretation.from_mapping(
            {
                "event_id": event.event_id,
                "cluster_id": event.cluster_id,
                "published_at": event.published_at,
                "summary": event.title[:240],
                "state_deltas": deltas,
                "novelty": novelty,
                "confidence": confidence,
                "source_quality": max(0.35, min(1.0, event.relevance_score)),
                "update_type": update_type,
                "evidence": [event.title[:280]],
                "uncertainties": ["Deterministic mock interpretation; no external model used."],
                "schema_version": "market-interpretation-v1",
                "model_version": self.model_version,
                "prompt_version": PROMPT_VERSION,
            }
        )
