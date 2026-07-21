from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
import hashlib
import re
from typing import Any, Iterable

from event_dna import SimilarEvent, find_similar_events
from event_models import MarketEvent
from telegram_query_builder import TelegramSearchPlan

REGIME_ID = "GEOPOLITICAL_CONFLICT"
TAXONOMY_VERSION = "geopolitical-conflict-v1"
MODEL_VERSION = "event-resolution-v1"

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9'-]+", re.IGNORECASE)
_FATALITY_RE = re.compile(r"\b(?:death toll|fatalities|killed|dead|deaths?)\D{0,18}(\d+)\b|\b(\d+)\s+(?:people|soldiers?|civilians?)?\s*(?:were\s+)?(?:killed|dead)\b", re.IGNORECASE)
_INJURY_RE = re.compile(r"\b(?:injured|wounded|injuries)\D{0,18}(\d+)\b|\b(\d+)\s+(?:people|soldiers?|civilians?)?\s*(?:were\s+)?(?:injured|wounded)\b", re.IGNORECASE)


class UpdateType(StrEnum):
    NEW_EVENT = "NEW_EVENT"
    UPDATE = "UPDATE"
    CONFIRMATION = "CONFIRMATION"
    ESCALATION = "ESCALATION"
    DEESCALATION = "DEESCALATION"
    CORRECTION = "CORRECTION"
    CONTEXT = "CONTEXT"
    DUPLICATE = "DUPLICATE"


@dataclass(frozen=True, slots=True)
class EventFacts:
    fatalities: int | None = None
    injuries: int | None = None
    confirmed: bool = False
    correction: bool = False

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CanonicalEvent:
    event_id: str
    cluster_id: str
    source_message_id: str
    source_url: str
    title: str
    event_type: str
    target: str
    country: str
    domain: str
    published_at: str | None
    relevance_score: float
    facts: EventFacts
    regime_id: str = REGIME_ID
    taxonomy_version: str = TAXONOMY_VERSION
    model_version: str = MODEL_VERSION

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["facts"] = self.facts.to_record()
        return record

    def to_market_event(self) -> MarketEvent:
        return MarketEvent(
            event_id=self.event_id,
            source="telegram",
            event_date=(self.published_at or "")[:10],
            title=self.title,
            summary=self.title,
            category=self.event_type,
            subcategory=self.event_type,
            domain=self.domain,
            country=self.country,
            location="",
            actors=[],
            confidence=self.relevance_score,
            market_sensitivity=self.relevance_score,
            significance=self.relevance_score,
            url=self.source_url,
            raw={
                "canonical": True,
                "cluster_id": self.cluster_id,
                "regime_id": self.regime_id,
                "taxonomy_version": self.taxonomy_version,
                "model_version": self.model_version,
                "target": self.target,
                "facts": self.facts.to_record(),
            },
            published_at=self.published_at,
            timestamp_source="telegram",
            timestamp_confidence=1.0 if self.published_at else 0.8,
        )


@dataclass(frozen=True, slots=True)
class ResolutionResult:
    update_type: UpdateType
    cluster_id: str
    similarity: float
    novelty_score: float
    severity_delta: float
    confidence_delta: float
    fact_changes: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["update_type"] = self.update_type.value
        return record


def _first_number(pattern: re.Pattern[str], text: str) -> int | None:
    match = pattern.search(text)
    if not match:
        return None
    value = next((group for group in match.groups() if group), None)
    return int(value) if value is not None else None


def extract_facts(text: str) -> EventFacts:
    lowered = text.lower()
    return EventFacts(
        fatalities=_first_number(_FATALITY_RE, text),
        injuries=_first_number(_INJURY_RE, text),
        confirmed=any(term in lowered for term in ("confirmed", "confirms", "officially", "verified")),
        correction=any(term in lowered for term in ("correction", "corrected", "was incorrect", "not true", "revised")),
    )


def canonical_event_from_plan(plan: TelegramSearchPlan) -> CanonicalEvent:
    event_id = f"telegram:{plan.message_url.rsplit('/', 2)[-2]}:{plan.message_id}"
    cluster_seed = "|".join((plan.event_type, plan.target, plan.country, " ".join(sorted(_tokens(plan.message_text))[:12])))
    cluster_id = "cluster:" + hashlib.sha1(cluster_seed.encode("utf-8")).hexdigest()[:16]
    return CanonicalEvent(
        event_id=event_id,
        cluster_id=cluster_id,
        source_message_id=plan.message_id,
        source_url=plan.message_url,
        title=plan.message_text,
        event_type=plan.event_type,
        target=plan.target,
        country=plan.country,
        domain=plan.domain,
        published_at=plan.published_at or None,
        relevance_score=min(1.0, max(0.0, plan.signal_score / 3.0)),
        facts=extract_facts(plan.message_text),
    )


def _tokens(text: str) -> set[str]:
    stop = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "at", "for", "is", "was", "were", "has", "have", "with", "from", "breaking"}
    return {token.lower() for token in _TOKEN_RE.findall(text) if len(token) > 2 and token.lower() not in stop}


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def resolve_observation(current: CanonicalEvent, previous: CanonicalEvent | None) -> ResolutionResult:
    if previous is None:
        return ResolutionResult(UpdateType.NEW_EVENT, current.cluster_id, 0.0, 1.0, 0.0, 0.0)

    text_similarity = _jaccard(_tokens(current.title), _tokens(previous.title))
    field_similarity = sum((current.event_type == previous.event_type, current.target == previous.target, current.country == previous.country)) / 3.0
    similarity = round(0.65 * text_similarity + 0.35 * field_similarity, 4)
    fact_changes: dict[str, dict[str, Any]] = {}
    for name in ("fatalities", "injuries", "confirmed"):
        old = getattr(previous.facts, name)
        new = getattr(current.facts, name)
        if new is not None and old != new:
            fact_changes[name] = {"old": old, "new": new}

    if current.title.strip().lower() == previous.title.strip().lower() or similarity >= 0.94:
        update_type = UpdateType.DUPLICATE
        novelty = severity_delta = confidence_delta = 0.0
    elif current.facts.correction:
        update_type = UpdateType.CORRECTION
        novelty, severity_delta, confidence_delta = 0.8, -0.25, -0.1
    elif previous.facts.fatalities is not None and current.facts.fatalities is not None and current.facts.fatalities > previous.facts.fatalities:
        update_type = UpdateType.ESCALATION
        novelty, severity_delta, confidence_delta = 0.9, min(0.5, 0.08 * (current.facts.fatalities - previous.facts.fatalities)), 0.05
    elif previous.facts.fatalities is not None and current.facts.fatalities is not None and current.facts.fatalities < previous.facts.fatalities:
        update_type = UpdateType.DEESCALATION
        novelty, severity_delta, confidence_delta = 0.9, -min(0.5, 0.08 * (previous.facts.fatalities - current.facts.fatalities)), 0.05
    elif current.facts.confirmed and not previous.facts.confirmed:
        update_type = UpdateType.CONFIRMATION
        novelty, severity_delta, confidence_delta = 0.65, 0.0, 0.2
    elif similarity >= 0.55:
        update_type = UpdateType.UPDATE
        novelty, severity_delta, confidence_delta = 0.55, 0.0, 0.05
    else:
        update_type = UpdateType.NEW_EVENT
        novelty, severity_delta, confidence_delta = 1.0, 0.0, 0.0

    cluster_id = previous.cluster_id if update_type is not UpdateType.NEW_EVENT else current.cluster_id
    return ResolutionResult(update_type, cluster_id, similarity, novelty, round(severity_delta, 4), round(confidence_delta, 4), fact_changes)


def rank_gdelt_analogues(canonical: CanonicalEvent, events: Iterable[MarketEvent], *, limit: int = 20, minimum_score: float = 0.2) -> list[SimilarEvent]:
    """Rank GDELT candidates against the Telegram event without changing its identity."""
    return find_similar_events(canonical.to_market_event(), events, limit=limit, minimum_score=minimum_score)
