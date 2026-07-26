import json

import pytest

from gdelt_ingestion import GdeltCandidateRecord
from semantic_analogue import OpenAIAnalogueAssessor, build_semantic_comparison_prompt
from telegram_query_builder import TelegramSearchPlan


def sample_source() -> TelegramSearchPlan:
    return TelegramSearchPlan(
        message_id="semantic-source-1",
        message_url="https://t.me/manual/semantic-source-1",
        message_text="Iran confirms a missile strike damaged an oil export terminal.",
        event_type="attack",
        target="energy infrastructure",
        country="Iran",
        domain="INFRASTRUCTURE",
        search="attack energy infrastructure Iran",
        signal_score=3,
        published_at="2026-07-25T12:00:00+00:00",
    )


def sample_candidate() -> GdeltCandidateRecord:
    return GdeltCandidateRecord(
        search_id="gdelt-search:semantic",
        event_id="gdelt-doc:semantic-candidate",
        provider="GDELT DOC",
        query="attack energy infrastructure Iran",
        title="Drone attack interrupts refinery exports",
        summary="A drone attack briefly interrupted exports from a regional refinery.",
        published_at="2025-05-10T08:00:00+00:00",
        event_date="2025-05-10",
        country="Saudi Arabia",
        domain="example.com",
        url="https://example.com/semantic-candidate",
        retrieved_at="2026-07-25T13:00:00+00:00",
        raw={"seendate": "20250510T080000Z"},
        schema_version="gdelt-candidate-v1",
    )


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(self.payload)


def test_prompt_keeps_semantic_judgement_open_but_separates_the_two_goals():
    prompt = build_semantic_comparison_prompt(sample_source(), sample_candidate())

    assert "Use any semantic, contextual, causal" in prompt
    assert "Do not rely only on shared words" in prompt
    assert "event_similarity" in prompt
    assert "market_similarity" in prompt
    assert sample_source().message_text in prompt
    assert sample_candidate().title in prompt


def test_openai_assessor_returns_two_scores_and_free_explanation():
    model_output = {
        "event_similarity": 0.78,
        "market_similarity": 0.64,
        "explanation": "Both are confirmed attacks on export infrastructure, but the actors and regional supply context differ.",
    }
    session = FakeSession(
        {
            "id": "resp_test",
            "output": [
                {
                    "content": [
                        {"type": "output_text", "text": json.dumps(model_output)}
                    ]
                }
            ],
        }
    )
    assessor = OpenAIAnalogueAssessor(
        api_key="test-key",
        model="gpt-test",
        session=session,
    )

    result = assessor.assess(sample_source(), sample_candidate())

    assert result.source_message_id == "semantic-source-1"
    assert result.candidate_event_id == "gdelt-doc:semantic-candidate"
    assert result.event_similarity == 0.78
    assert result.market_similarity == 0.64
    assert result.explanation.startswith("Both are confirmed")
    assert result.model == "gpt-test"
    assert result.assessment_version == "semantic-analogue-v1"
    request_body = session.calls[0][1]["json"]
    assert request_body["text"]["format"]["type"] == "json_schema"
    assert request_body["text"]["format"]["strict"] is True


def test_openai_assessor_rejects_out_of_range_scores():
    session = FakeSession(
        {
            "output_text": json.dumps(
                {
                    "event_similarity": 1.2,
                    "market_similarity": 0.4,
                    "explanation": "Invalid score for testing.",
                }
            )
        }
    )
    assessor = OpenAIAnalogueAssessor(
        api_key="test-key",
        model="gpt-test",
        session=session,
    )

    with pytest.raises(ValueError, match="event_similarity must be between 0 and 1"):
        assessor.assess(sample_source(), sample_candidate())
