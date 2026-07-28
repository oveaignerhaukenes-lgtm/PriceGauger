from gdelt_ingestion import GdeltCandidateRecord
from semantic_analogue import AnalogueAssessment
from semantic_analogue_ranking import rank_analogues
from telegram_query_builder import TelegramSearchPlan


class FakeAssessor:
    def assess(self, source, candidate):
        event_score = 0.9 if candidate.event_id == "candidate-a" else 0.3
        return AnalogueAssessment(
            source_message_id=source.message_id,
            candidate_event_id=candidate.event_id,
            event_similarity=event_score,
            market_similarity=event_score - 0.1,
            explanation="test explanation",
            model="fake-model",
            assessment_version="test",
            raw={},
        )


def candidate(event_id):
    return GdeltCandidateRecord(
        search_id="search-1",
        event_id=event_id,
        provider="GDELT BigQuery",
        query="oil shipping disruption",
        title=event_id,
        summary="summary",
        published_at="2026-07-01T12:00:00+00:00",
        event_date="2026-07-01",
        country="IR",
        domain="example.com",
        url="https://example.com/" + event_id,
        retrieved_at="2026-07-28T12:00:00+00:00",
        raw={},
    )


def test_rank_analogues_orders_by_combined_similarity():
    source = TelegramSearchPlan(
        message_id="42",
        message_url="https://t.me/example/42",
        message_text="Shipping disruption near Hormuz",
        event_type="shipping disruption",
        target="commercial shipping",
        country="",
        domain="INFRASTRUCTURE",
        search="Hormuz shipping disruption",
        signal_score=3,
    )
    ranked = rank_analogues(
        source,
        [candidate("candidate-b"), candidate("candidate-a")],
        assessor=FakeAssessor(),
    )
    assert [item.candidate_event_id for item in ranked] == ["candidate-a", "candidate-b"]
    assert ranked[0].combined_similarity == 0.85
