from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

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
        combined = 0.5 * assessment.event_similarity + 0.5 * assessment.market_similarity
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
