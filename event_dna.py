from __future__ import annotations

from dataclasses import asdict, dataclass
from math import sqrt
import re
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

from event_models import MarketEvent

_TOKEN_RE = re.compile(r"[\w'-]+", re.UNICODE)

_EVENT_TYPE_TERMS: dict[str, tuple[str, ...]] = {
    "attack": ("attack", "strike", "bomb", "missile", "drone", "shelling", "airstrike"),
    "blockade": ("blockade", "closure", "closed", "shut", "halted", "disrupted"),
    "sanctions": ("sanction", "embargo", "export ban", "restriction"),
    "diplomacy": ("talks", "negotiation", "ceasefire", "agreement", "meeting", "deal"),
    "production": ("production", "output", "supply", "quota", "cut", "increase"),
    "macro": ("inflation", "ppi", "cpi", "rates", "interest rate", "employment", "payroll"),
}

_TARGET_TERMS: dict[str, tuple[str, ...]] = {
    "energy_infrastructure": ("refinery", "pipeline", "oilfield", "terminal", "tanker", "lng", "gas field"),
    "shipping": ("ship", "vessel", "tanker", "port", "strait", "shipping", "maritime"),
    "military": ("base", "airbase", "troops", "military", "navy", "army", "irgc"),
    "civilian": ("civilian", "residential", "hospital", "school"),
    "government": ("government", "ministry", "president", "parliament", "embassy"),
}


def _normalise(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _tokens(value: Any) -> frozenset[str]:
    return frozenset(token for token in _TOKEN_RE.findall(_normalise(value)) if len(token) > 1)


def _bounded(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, number))


def _first_term(text: str, groups: Mapping[str, Sequence[str]], default: str) -> str:
    for label, terms in groups.items():
        if any(term in text for term in terms):
            return label
    return default


@dataclass(frozen=True, slots=True)
class EventDNA:
    event_id: str
    event_type: str
    category: str
    subcategory: str
    domain: str
    country: str
    location: str
    actors: tuple[str, ...]
    target: str
    severity: float
    source_quality: float
    market_sensitivity: float
    significance: float
    title_tokens: frozenset[str]
    summary_tokens: frozenset[str]

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["actors"] = list(self.actors)
        record["title_tokens"] = sorted(self.title_tokens)
        record["summary_tokens"] = sorted(self.summary_tokens)
        return record


@dataclass(frozen=True, slots=True)
class SimilarEvent:
    event_id: str
    score: float
    components: dict[str, float]
    event: MarketEvent
    dna: EventDNA

    def to_record(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "score": self.score,
            "components": dict(self.components),
            "event": self.event.to_record(),
            "dna": self.dna.to_record(),
        }


@dataclass(frozen=True, slots=True)
class MarketProfile:
    asset: str
    sample_size: int
    effective_sample_size: float
    positive_share_pct: float | None
    median_1h_pct: float | None
    median_4h_pct: float | None
    median_24h_pct: float | None
    weighted_mean_1h_pct: float | None
    weighted_mean_4h_pct: float | None
    weighted_mean_24h_pct: float | None
    median_max_up_24h_pct: float | None
    median_max_down_24h_pct: float | None
    confidence_pct: float
    direction: str

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


def build_event_dna(event: MarketEvent) -> EventDNA:
    text = _normalise(" ".join((event.title, event.summary, event.category, event.subcategory)))
    event_type = _first_term(text, _EVENT_TYPE_TERMS, _normalise(event.subcategory) or _normalise(event.category) or "unknown")
    target = _first_term(text, _TARGET_TERMS, "unspecified")

    confidence = _bounded(event.confidence, 0.5)
    timestamp_confidence = _bounded(event.timestamp_confidence, confidence)
    source_quality = (confidence * 0.7) + (timestamp_confidence * 0.3)
    market_sensitivity = _bounded(event.market_sensitivity)
    significance = _bounded(event.significance)
    severity = max(significance, (market_sensitivity * 0.65) + (significance * 0.35))

    return EventDNA(
        event_id=event.event_id,
        event_type=event_type,
        category=_normalise(event.category),
        subcategory=_normalise(event.subcategory),
        domain=_normalise(event.domain),
        country=_normalise(event.country),
        location=_normalise(event.location),
        actors=tuple(sorted({_normalise(actor) for actor in event.actors if _normalise(actor)})),
        target=target,
        severity=round(severity, 4),
        source_quality=round(source_quality, 4),
        market_sensitivity=round(market_sensitivity, 4),
        significance=round(significance, 4),
        title_tokens=_tokens(event.title),
        summary_tokens=_tokens(event.summary),
    )


def _jaccard(left: frozenset[str] | set[str], right: frozenset[str] | set[str]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _exact(left: str, right: str, *, empty_score: float = 0.0) -> float:
    if not left or not right:
        return empty_score
    return 1.0 if left == right else 0.0


def event_similarity(left: EventDNA, right: EventDNA) -> tuple[float, dict[str, float]]:
    components = {
        "event_type": _exact(left.event_type, right.event_type),
        "category": _exact(left.category, right.category),
        "subcategory": _exact(left.subcategory, right.subcategory),
        "domain": _exact(left.domain, right.domain),
        "country": _exact(left.country, right.country),
        "location": _exact(left.location, right.location),
        "actors": _jaccard(set(left.actors), set(right.actors)),
        "target": _exact(left.target, right.target),
        "title": _jaccard(left.title_tokens, right.title_tokens),
        "summary": _jaccard(left.summary_tokens, right.summary_tokens),
        "severity": 1.0 - abs(left.severity - right.severity),
        "source_quality": 1.0 - abs(left.source_quality - right.source_quality),
    }
    weights = {
        "event_type": 0.18,
        "category": 0.08,
        "subcategory": 0.06,
        "domain": 0.06,
        "country": 0.10,
        "location": 0.05,
        "actors": 0.12,
        "target": 0.10,
        "title": 0.08,
        "summary": 0.07,
        "severity": 0.07,
        "source_quality": 0.03,
    }
    score = sum(components[name] * weight for name, weight in weights.items())
    return round(max(0.0, min(1.0, score)), 6), {key: round(value, 6) for key, value in components.items()}


def find_similar_events(
    query: MarketEvent | EventDNA,
    candidates: Iterable[MarketEvent],
    *,
    limit: int = 20,
    minimum_score: float = 0.20,
) -> list[SimilarEvent]:
    query_dna = query if isinstance(query, EventDNA) else build_event_dna(query)
    matches: list[SimilarEvent] = []
    for event in candidates:
        if event.event_id == query_dna.event_id:
            continue
        dna = build_event_dna(event)
        score, components = event_similarity(query_dna, dna)
        if score >= minimum_score:
            matches.append(SimilarEvent(event.event_id, score, components, event, dna))
    matches.sort(key=lambda item: (item.score, item.dna.source_quality, item.dna.severity), reverse=True)
    return matches[: max(0, limit)]


def _reaction_record(item: Any) -> dict[str, Any]:
    if hasattr(item, "to_record"):
        return dict(item.to_record())
    if isinstance(item, Mapping):
        return dict(item)
    return dict(vars(item))


def _weighted_mean(values: pd.Series, weights: pd.Series) -> float | None:
    mask = values.notna() & weights.notna() & (weights > 0)
    if not mask.any():
        return None
    usable_values = values[mask].astype(float)
    usable_weights = weights[mask].astype(float)
    total = float(usable_weights.sum())
    return float((usable_values * usable_weights).sum() / total) if total else None


def build_market_profile(
    *,
    asset: str,
    similar_events: Iterable[SimilarEvent],
    reactions: Iterable[Any],
) -> MarketProfile:
    similarities = {item.event_id: item.score for item in similar_events}
    rows: list[dict[str, Any]] = []
    for reaction in reactions:
        record = _reaction_record(reaction)
        event_id = str(record.get("event_id") or "")
        if event_id not in similarities or record.get("asset") != asset:
            continue
        quality = _bounded(record.get("quality_score"), 1.0)
        record["weight"] = similarities[event_id] * max(0.1, quality)
        rows.append(record)

    frame = pd.DataFrame(rows)
    if frame.empty:
        return MarketProfile(asset, 0, 0.0, None, None, None, None, None, None, None, None, None, 0.0, "NEUTRAL")

    weights = pd.to_numeric(frame["weight"], errors="coerce").fillna(0.0)
    returns: dict[str, pd.Series] = {}
    for horizon in ("1h", "4h", "24h"):
        returns[horizon] = pd.to_numeric(frame.get(f"return_{horizon}_pct", pd.Series(index=frame.index, dtype=float)), errors="coerce")

    one_hour = returns["1h"].dropna()
    positive_share = float((one_hour > 0).mean() * 100.0) if not one_hour.empty else None
    medians = {key: (float(series.dropna().median()) if not series.dropna().empty else None) for key, series in returns.items()}
    means = {key: _weighted_mean(series, weights) for key, series in returns.items()}

    max_up = pd.to_numeric(frame.get("max_up_24h_pct", pd.Series(index=frame.index, dtype=float)), errors="coerce").dropna()
    max_down = pd.to_numeric(frame.get("max_down_24h_pct", pd.Series(index=frame.index, dtype=float)), errors="coerce").dropna()
    effective_n = (float(weights.sum()) ** 2 / float((weights ** 2).sum())) if float((weights ** 2).sum()) > 0 else 0.0
    directional = means["4h"] if means["4h"] is not None else means["1h"]
    direction = "LONG" if directional is not None and directional > 0.05 else "SHORT" if directional is not None and directional < -0.05 else "NEUTRAL"
    confidence = min(95.0, (sqrt(effective_n) * 18.0) + (abs((positive_share or 50.0) - 50.0) * 0.5))

    return MarketProfile(
        asset=asset,
        sample_size=len(frame),
        effective_sample_size=round(effective_n, 3),
        positive_share_pct=round(positive_share, 3) if positive_share is not None else None,
        median_1h_pct=round(medians["1h"], 6) if medians["1h"] is not None else None,
        median_4h_pct=round(medians["4h"], 6) if medians["4h"] is not None else None,
        median_24h_pct=round(medians["24h"], 6) if medians["24h"] is not None else None,
        weighted_mean_1h_pct=round(means["1h"], 6) if means["1h"] is not None else None,
        weighted_mean_4h_pct=round(means["4h"], 6) if means["4h"] is not None else None,
        weighted_mean_24h_pct=round(means["24h"], 6) if means["24h"] is not None else None,
        median_max_up_24h_pct=round(float(max_up.median()), 6) if not max_up.empty else None,
        median_max_down_24h_pct=round(float(max_down.median()), 6) if not max_down.empty else None,
        confidence_pct=round(confidence, 1),
        direction=direction,
    )
