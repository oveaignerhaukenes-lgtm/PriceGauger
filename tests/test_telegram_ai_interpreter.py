import json

from telegram_ai_interpreter import OpenAITelegramInterpreter, interpret_search_plan
from telegram_query_builder import TelegramSearchPlan


class FakeResponse:
    ok = True
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {
            "output_text": json.dumps(
                {
                    "event_type": "military de-escalation claim",
                    "actor": "Iran",
                    "target": "US military escalation expectations",
                    "country": "Iran",
                    "market_channel": "reduced geopolitical oil-risk premium",
                    "search_terms": [
                        "Iran de-escalation",
                        "US military restraint",
                        "Middle East conflict pause",
                        "oil risk premium",
                    ],
                    "confidence": 0.82,
                }
            )
        }


class FakeSession:
    def __init__(self):
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse()


def sample_plan() -> TelegramSearchPlan:
    return TelegramSearchPlan(
        message_id="42",
        message_url="https://t.me/example/42",
        message_text="Sources say Iran has no intention to escalate with the United States.",
        event_type="event",
        target="unspecified",
        country="Iran",
        domain="",
        search="Iran sources intention escalate",
        signal_score=1,
        published_at="2026-07-28T12:00:00Z",
    )


def test_openai_interpreter_builds_compact_structured_search_plan():
    session = FakeSession()
    interpreted = OpenAITelegramInterpreter(
        api_key="test-key",
        model="test-model",
        session=session,
    ).interpret(sample_plan())

    assert interpreted.event_type == "military de-escalation claim"
    assert interpreted.actor == "Iran"
    assert interpreted.country == "Iran"
    assert interpreted.market_channel == "reduced geopolitical oil-risk premium"
    assert interpreted.search_terms == (
        "Iran de-escalation",
        "US military restraint",
        "Middle East conflict pause",
        "oil risk premium",
    )
    assert interpreted.search == " ".join(interpreted.search_terms)
    assert interpreted.interpretation_source == "openai"
    assert interpreted.interpretation_model == "test-model"
    assert interpreted.interpretation_confidence == 0.82
    assert interpreted.signal_score == 3

    request = session.calls[0][1]["json"]
    schema = request["text"]["format"]["schema"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["search_terms"]["maxItems"] == 6
    assert "SQL" in request["input"]


def test_interpret_search_plan_preserves_rules_when_openai_is_not_configured(monkeypatch):
    plan = sample_plan()
    monkeypatch.setattr("telegram_ai_interpreter.openai_api_key", lambda: "")

    assert interpret_search_plan(plan) is plan
