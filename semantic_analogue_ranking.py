from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from gdelt_ingestion import GdeltCandidateRecord
from semantic_analogue import AnalogueAssessor, OpenAIAnalogueAssessor
from telegram_query_builder import TelegramSearchPlan


@dataclass(frozen=True, slots=True)
class RankedAnalogue:
    candidate_event_id: str
    title: str
    published_at: str
    event_similarity: float
    market_similarity: float
    combined_similarity: float
    explanation: str
    model: str

    def to_record(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AnalogueSelection:
    selected_reactions: tuple[dict[str, Any], ...]
    selected_event_ids: tuple[str, ...]
    excluded_event_ids: tuple[str, ...]
    minimum_event_similarity: float
    minimum_market_similarity: float
    minimum_combined_similarity: float

    @property
    def selected_count(self) -> int:
        return len(self.selected_event_ids)

    @property
    def excluded_count(self) -> int:
        return len(self.excluded_event_ids)


def rank_analogues(
    source: TelegramSearchPlan,
    candidates: Iterable[GdeltCandidateRecord],
    *,
    assessor: AnalogueAssessor | None = None,
    limit: int = 10,
) -> list[RankedAnalogue]:
    active_assessor = assessor or OpenAIAnalogueAssessor()
    ranked: list[RankedAnalogue] = []

    for candidate in list(candidates)[: max(1, int(limit))]:
        assessment = active_assessor.assess(source, candidate)
        combined = round(
            0.5 * assessment.event_similarity + 0.5 * assessment.market_similarity,
            12,
        )
        ranked.append(
            RankedAnalogue(
                candidate_event_id=candidate.event_id,
                title=candidate.title,
                published_at=candidate.published_at or candidate.event_date,
                event_similarity=assessment.event_similarity,
                market_similarity=assessment.market_similarity,
                combined_similarity=combined,
                explanation=assessment.explanation,
                model=assessment.model,
            )
        )

    return sorted(ranked, key=lambda item: item.combined_similarity, reverse=True)


def select_reactions_for_ranked_analogues(
    reactions: Iterable[dict[str, Any]],
    rankings: Iterable[dict[str, Any]],
    *,
    minimum_event_similarity: float = 0.60,
    minimum_market_similarity: float = 0.50,
    minimum_combined_similarity: float = 0.60,
    maximum_analogues: int = 8,
) -> AnalogueSelection:
    """Keep only semantically relevant reactions, in ranking order.

    This deliberately rejects weak candidates rather than allowing unrelated GDELT
    rows to determine the price direction. Market-regime filtering is a later layer.
    """
    reaction_by_id = {
        str(row.get("candidate_event_id") or ""): dict(row)
        for row in reactions
        if str(row.get("candidate_event_id") or "")
    }

    selected_ids: list[str] = []
    excluded_ids: list[str] = []
    for item in rankings:
        event_id = str(item.get("candidate_event_id") or "")
        if not event_id or event_id not in reaction_by_id:
            continue
        event_score = float(item.get("event_similarity") or 0.0)
        market_score = float(item.get("market_similarity") or 0.0)
        combined_score = float(item.get("combined_similarity") or 0.0)
        passes = (
            event_score >= minimum_event_similarity
            and market_score >= minimum_market_similarity
            and combined_score >= minimum_combined_similarity
        )
        if passes and len(selected_ids) < max(1, int(maximum_analogues)):
            selected_ids.append(event_id)
        else:
            excluded_ids.append(event_id)

    selected_rows = tuple(reaction_by_id[event_id] for event_id in selected_ids)
    return AnalogueSelection(
        selected_reactions=selected_rows,
        selected_event_ids=tuple(selected_ids),
        excluded_event_ids=tuple(excluded_ids),
        minimum_event_similarity=minimum_event_similarity,
        minimum_market_similarity=minimum_market_similarity,
        minimum_combined_similarity=minimum_combined_similarity,
    )
