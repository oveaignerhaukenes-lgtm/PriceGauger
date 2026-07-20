from __future__ import annotations

from dataclasses import asdict, dataclass
from math import exp, log
from typing import Any, Iterable, Mapping

import pandas as pd

from decision_engine import MarketAssessment, build_market_assessment
from event_dna import build_event_dna, build_market_profile, find_similar_events
from event_models import MarketEvent


_DIRECTION_SIGN = {"LONG": 1.0, "SHORT": -1.0, "NEUTRAL": 0.0}
_EVIDENCE_FACTOR = {"HIGH": 1.0, "MEDIUM": 0.85, "LOW": 0.65, "INSUFFICIENT": 0.0}


@dataclass(frozen=True, slots=True)
class EventSignal:
    event_id: str
    title: str
    published_at: str
    event_type: str
    target: str
    direction: str
    confidence_pct: float
    expected_move_pct: float | None
    evidence_grade: str
    analogue_sample: int
    effective_analogue_sample: float
    source_quality: float
    severity: float
    age_hours: float
    freshness_weight: float
    signal_weight: float
    contribution: float

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AggregateSignal:
    asset: str
    window_hours: int
    events_considered: int
    events_used: int
    long_events: int
    short_events: int
    neutral_events: int
    net_score: float
    direction: str
    confidence_pct: float
    expected_move_pct: float | None
    agreement_pct: float
    effective_event_count: float
    evidence_grade: str
    rationale: tuple[str, ...]
    event_signals: tuple[EventSignal, ...]

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["event_signals"] = [item.to_record() for item in self.event_signals]
        record["rationale"] = list(self.rationale)
        return record

    def to_market_assessment(self) -> MarketAssessment:
        positive_share = None
        directional = self.long_events + self.short_events
        if directional:
            positive_share = self.long_events / directional * 100.0
        return MarketAssessment(
            asset=self.asset,
            direction=self.direction,
            confidence_pct=self.confidence_pct,
            expected_move_pct=self.expected_move_pct,
            horizon=f"0–{self.window_hours} timer",
            historical_sample=self.events_used,
            historical_positive_share_pct=positive_share,
            historical_median_pct=self.expected_move_pct,
            live_event_score=self.net_score,
            momentum_pct=None,
            evidence_grade=self.evidence_grade,
            rationale=list(self.rationale),
        )


def _event_timestamp(event: MarketEvent) -> pd.Timestamp | None:
    value = getattr(event, "published_at", None) or getattr(event, "event_date", None)
    parsed = pd.to_datetime(value, utc=True, errors="coerce")
    return None if pd.isna(parsed) else parsed


def _reaction_record(item: Any) -> dict[str, Any]:
    if hasattr(item, "to_record"):
        return dict(item.to_record())
    if isinstance(item, Mapping):
        return dict(item)
    return dict(vars(item))


def _historical_candidates(query: MarketEvent, events: Iterable[MarketEvent]) -> list[MarketEvent]:
    query_time = _event_timestamp(query)
    candidates: list[MarketEvent] = []
    for event in events:
        if event.event_id == query.event_id:
            continue
        event_time = _event_timestamp(event)
        # Avoid future leakage when the event collection spans several dates.
        if query_time is not None and event_time is not None and event_time >= query_time:
            continue
        candidates.append(event)
    return candidates


def build_event_signals(
    *,
    events: Iterable[MarketEvent],
    reactions: Iterable[Any],
    asset: str,
    window_hours: int = 24,
    half_life_hours: float = 6.0,
    now: pd.Timestamp | None = None,
    minimum_similarity: float = 0.20,
    analogue_limit: int = 20,
) -> list[EventSignal]:
    """Score each recent event independently before any cross-event aggregation.

    Historical analogues are found per event. The events are only combined after each
    event has its own Market Profile and MarketAssessment, preventing combinatorial
    analogue sparsity from a composite EventDNA query.
    """
    current = now or pd.Timestamp.now(tz="UTC")
    if current.tzinfo is None:
        current = current.tz_localize("UTC")
    else:
        current = current.tz_convert("UTC")

    event_list = list(events)
    reaction_list = list(reactions)
    cutoff = current - pd.Timedelta(hours=max(1, int(window_hours)))
    half_life = max(0.25, float(half_life_hours))
    decay_constant = log(2.0) / half_life
    results: list[EventSignal] = []

    for event in event_list:
        timestamp = _event_timestamp(event)
        if timestamp is None or timestamp < cutoff or timestamp > current + pd.Timedelta(minutes=15):
            continue

        dna = build_event_dna(event)
        candidates = _historical_candidates(event, event_list)
        matches = find_similar_events(
            event,
            candidates,
            limit=analogue_limit,
            minimum_score=minimum_similarity,
        )
        profile = build_market_profile(asset=asset, similar_events=matches, reactions=reaction_list)
        assessment = build_market_assessment(
            asset=asset,
            messages=pd.DataFrame(),
            market=pd.DataFrame(),
            intraday_reactions=reaction_list,
            market_profile=profile,
        )

        age_hours = max(0.0, (current - timestamp).total_seconds() / 3600.0)
        freshness = exp(-decay_constant * age_hours)
        evidence_factor = _EVIDENCE_FACTOR.get(assessment.evidence_grade, 0.5)
        confidence_factor = max(0.0, min(1.0, assessment.confidence_pct / 100.0))
        source_factor = 0.50 + 0.50 * max(0.0, min(1.0, dna.source_quality))
        severity_factor = 0.60 + 0.40 * max(0.0, min(1.0, dna.severity))
        sample_factor = min(1.0, max(0.0, profile.effective_sample_size) / 5.0)
        signal_weight = freshness * evidence_factor * confidence_factor * source_factor * severity_factor * sample_factor

        direction_sign = _DIRECTION_SIGN.get(assessment.direction, 0.0)
        move = float(assessment.expected_move_pct or 0.0)
        magnitude = min(1.0, abs(move) / 0.50) if move else 0.0
        contribution = direction_sign * signal_weight * magnitude

        results.append(
            EventSignal(
                event_id=event.event_id,
                title=str(event.title or ""),
                published_at=timestamp.isoformat(),
                event_type=dna.event_type,
                target=dna.target,
                direction=assessment.direction,
                confidence_pct=assessment.confidence_pct,
                expected_move_pct=assessment.expected_move_pct,
                evidence_grade=assessment.evidence_grade,
                analogue_sample=profile.sample_size,
                effective_analogue_sample=profile.effective_sample_size,
                source_quality=dna.source_quality,
                severity=dna.severity,
                age_hours=round(age_hours, 3),
                freshness_weight=round(freshness, 6),
                signal_weight=round(signal_weight, 6),
                contribution=round(contribution, 6),
            )
        )

    results.sort(key=lambda item: (item.signal_weight, -item.age_hours), reverse=True)
    return results


def aggregate_event_signals(
    *,
    asset: str,
    signals: Iterable[EventSignal],
    window_hours: int = 24,
    dead_zone: float = 0.12,
) -> AggregateSignal:
    items = list(signals)
    usable = [
        item
        for item in items
        if item.signal_weight > 0
        and item.direction in {"LONG", "SHORT"}
        and item.expected_move_pct is not None
        and item.evidence_grade != "INSUFFICIENT"
    ]

    total_weight = sum(item.signal_weight for item in usable)
    net_score = sum(item.contribution for item in usable) / total_weight if total_weight else 0.0
    direction = "LONG" if net_score > dead_zone else "SHORT" if net_score < -dead_zone else "NEUTRAL"

    expected_move = None
    if total_weight:
        expected_move = sum(float(item.expected_move_pct or 0.0) * item.signal_weight for item in usable) / total_weight

    long_count = sum(item.direction == "LONG" for item in usable)
    short_count = sum(item.direction == "SHORT" for item in usable)
    neutral_count = len(items) - long_count - short_count

    matching_weight = sum(item.signal_weight for item in usable if item.direction == direction)
    agreement = matching_weight / total_weight * 100.0 if total_weight and direction != "NEUTRAL" else 0.0
    weight_squares = sum(item.signal_weight**2 for item in usable)
    effective_n = total_weight**2 / weight_squares if weight_squares else 0.0
    average_confidence = (
        sum(item.confidence_pct * item.signal_weight for item in usable) / total_weight if total_weight else 0.0
    )
    confidence = min(
        95.0,
        (agreement * 0.45)
        + (min(1.0, effective_n / 5.0) * 30.0)
        + (average_confidence * 0.25),
    )

    if len(usable) < 2 or effective_n < 1.5:
        evidence_grade = "INSUFFICIENT"
    elif confidence >= 80.0 and agreement >= 70.0:
        evidence_grade = "HIGH"
    elif confidence >= 65.0 and agreement >= 60.0:
        evidence_grade = "MEDIUM"
    else:
        evidence_grade = "LOW"

    if evidence_grade == "INSUFFICIENT":
        direction = "NEUTRAL"

    rationale = (
        f"{len(usable)} av {len(items)} hendelser hadde brukbart historisk signal.",
        f"Retningsenighet: {agreement:.1f} %, effektivt hendelsesutvalg: {effective_n:.2f}.",
        f"Netto tidsvektet signal: {net_score:+.3f} innenfor et {window_hours}-timers vindu.",
        "Hver hendelse er først matchet mot egne historiske analoger; bare de ferdige hendelsessignalene summeres.",
    )

    return AggregateSignal(
        asset=asset,
        window_hours=window_hours,
        events_considered=len(items),
        events_used=len(usable),
        long_events=long_count,
        short_events=short_count,
        neutral_events=neutral_count,
        net_score=round(net_score, 6),
        direction=direction,
        confidence_pct=round(max(0.0, confidence), 1),
        expected_move_pct=round(expected_move, 6) if expected_move is not None else None,
        agreement_pct=round(agreement, 1),
        effective_event_count=round(effective_n, 3),
        evidence_grade=evidence_grade,
        rationale=rationale,
        event_signals=tuple(items),
    )


def build_aggregate_signal(
    *,
    events: Iterable[MarketEvent],
    reactions: Iterable[Any],
    asset: str,
    window_hours: int = 24,
    half_life_hours: float = 6.0,
    now: pd.Timestamp | None = None,
    minimum_similarity: float = 0.20,
    analogue_limit: int = 20,
) -> AggregateSignal:
    signals = build_event_signals(
        events=events,
        reactions=reactions,
        asset=asset,
        window_hours=window_hours,
        half_life_hours=half_life_hours,
        now=now,
        minimum_similarity=minimum_similarity,
        analogue_limit=analogue_limit,
    )
    return aggregate_event_signals(asset=asset, signals=signals, window_hours=window_hours)
