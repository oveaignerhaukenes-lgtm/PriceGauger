from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from enum import StrEnum
import hashlib
import re
from typing import Any, Iterable

from event_dna import SimilarEvent, find_similar_events
from event_models import MarketEvent
from telegram_query_builder import TelegramSearchPlan

REGIME_ID = "GEOPOLITICAL_CONFLICT"
TAXONOMY_VERSION = "geopolitical-conflict-v1"
MODEL_VERSION = "event-resolution-v2"

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9'-]+", re.IGNORECASE)
_FATALITY_RE = re.compile(r"\b(?:death toll|fatalities|killed|dead|deaths?)\D{0,18}(\d+)\b|\b(\d+)\s+(?:people|soldiers?|civilians?)?\s*(?:were\s+)?(?:killed|dead)\b", re.IGNORECASE)
_INJURY_RE = re.compile(r"\b(?:injured|wounded|injuries)\D{0,18}(\d+)\b|\b(\d+)\s+(?:people|soldiers?|civilians?)?\s*(?:were\s+)?(?:injured|wounded)\b", re.IGNORECASE)

_ATTACK_TERMS = (
    "attack", "attacked", "strike", "strikes", "struck", "bomb", "bombed",
    "bombing", "missile", "drone", "shelling", "airstrike", "explosion",
)
_ATTACK_WARNING_TERMS = ("air raid siren", "air-raid siren", "sirens sound", "incoming missile", "incoming drone")
_DIPLOMACY_TERMS = (
    "meeting", "meets", "met with", "talks", "telephone", "phone call", "discuss",
    "condemns", "statement", "tribute", "mourn", "half-mast", "sympathy", "condolence",
)
_TARGET_TERMS: dict[str, tuple[str, ...]] = {
    "diplomatic facility": ("embassy", "consulate", "diplomatic mission"),
    "energy_infrastructure": ("refinery", "pipeline", "oilfield", "oil field", "terminal", "lng", "gas field"),
    "shipping": ("ship", "ships", "vessel", "vessels", "tanker", "tankers", "port", "strait", "shipping", "maritime"),
    "military": ("airbase", "military base", "army base", "troops", "military", "navy", "army", "irgc"),
    "civilian": ("civilian", "residential", "hospital", "school"),
    "government": ("government", "ministry", "president", "parliament", "palace"),
}


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


def _contains_term(text: str, term: str) -> bool:
    words = r"\s+".join(re.escape(part) for part in term.lower().split())
    return re.search(rf"(?<![a-z0-9]){words}(?![a-z0-9])", text.lower()) is not None


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    return any(_contains_term(text, term) for term in terms)


def _candidate_text(event: MarketEvent) -> str:
    return " ".join((event.title or "", event.summary or "", event.category or "", event.subcategory or ""))


def _conflict_event_type(event: MarketEvent) -> str:
    text = _candidate_text(event)
    if _contains_any(text, _ATTACK_TERMS):
        return "attack"
    if _contains_any(text, _ATTACK_WARNING_TERMS):
        return "attack_warning"
    if _contains_any(text, _DIPLOMACY_TERMS):
        return "diplomacy"
    return "other"


def _conflict_target(event: MarketEvent) -> str:
    text = _candidate_text(event)
    for target, terms in _TARGET_TERMS.items():
        if _contains_any(text, terms):
            return target
    return "unspecified"


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


def rank_gdelt_analogues(
    canonical: CanonicalEvent,
    events: Iterable[MarketEvent],
    *,
    limit: int = 20,
    minimum_score: float = 0.2,
) -> list[SimilarEvent]:
    """Rank analogues by causal event semantics before generic metadata similarity."""
    candidates = list(events)
    generic = find_similar_events(
        canonical.to_market_event(),
        candidates,
        limit=max(100, len(candidates)),
        minimum_score=0.0,
    )
    query_tokens = _tokens(canonical.title)
    ranked: list[SimilarEvent] = []

    for item in generic:
        event_type = _conflict_event_type(item.event)
        target = _conflict_target(item.event)
        country_match = bool(canonical.country) and canonical.country.lower() == str(item.event.country or "").lower()
        lexical = _jaccard(query_tokens, _tokens(_candidate_text(item.event)))

        if canonical.event_type == "attack":
            action_score = 1.0 if event_type == "attack" else 0.72 if event_type == "attack_warning" else 0.0
        else:
            action_score = 1.0 if event_type == canonical.event_type else 0.0

        if canonical.target == target:
            target_score = 1.0
        elif target == "unspecified":
            target_score = 0.25
        elif canonical.target == "diplomatic facility" and target == "government":
            target_score = 0.45
        else:
            target_score = 0.0

        quality = (item.dna.source_quality + item.dna.severity) / 2.0
        score = (
            0.48 * action_score
            + 0.20 * target_score
            + 0.12 * float(country_match)
            + 0.15 * lexical
            + 0.05 * quality
        )

        # Non-violent context must never outrank a causally similar conflict event.
        if canonical.event_type == "attack" and event_type not in {"attack", "attack_warning"}:
            score = min(score, 0.18)
        elif canonical.event_type == "attack" and event_type == "attack_warning":
            score = min(score, 0.72)

        corrected_dna = replace(item.dna, event_type=event_type, target=target)
        components = dict(item.components)
        components.update(
            {
                "conflict_action": round(action_score, 6),
                "conflict_target": round(target_score, 6),
                "country_gate": float(country_match),
                "lexical_overlap": round(lexical, 6),
                "generic_score": item.score,
            }
        )
        score = round(max(0.0, min(1.0, score)), 6)
        if score >= minimum_score:
            ranked.append(SimilarEvent(item.event_id, score, components, item.event, corrected_dna))

    ranked.sort(key=lambda match: (match.score, match.dna.source_quality, match.dna.severity), reverse=True)
    return ranked[: max(0, limit)]
