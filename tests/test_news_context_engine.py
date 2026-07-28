import json

from news_context_engine import OpenAINewsContextEngine, build_windows
from telegram_query_builder import TelegramSearchPlan


def _plan(message_id: str, published_at: str, text: str) -> TelegramSearchPlan:
    return TelegramSearchPlan(
        message_id=message_id,
        message_url=f"https://t.me/example/{message_id}",
        message_text=text,
        event_type="event",
        target="unspecified",
        country="",
        domain="",
        search="event context",
        signal_score=2,
        published_at=published_at,
    )


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "output_text": json.dumps(
                {
                    "conflict_level": 0.8,
                    "fear_level": 0.65,
                    "escalation_direction": "escalating",
                    "physical_supply_risk": 0.55,
                    "narrative_saturation": 0.7,
                    "confirmation_quality": 0.6,
                    "regime_label": "sustained regional escalation",
                    "active_drivers": ["shipping threats"],
                    "counter_signals": ["no confirmed closure"],
                    "unresolved_questions": ["whether traffic is reduced"],
                    "summary": "Escalation is elevated but physical disruption is not confirmed.",
                    "confidence": 0.72,
                }
            )
        }


class FakeSession:
    def __init__(self):
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse()


def test_build_windows_uses_same_as_of_boundary_for_all_horizons():
    plans = [
        _plan("1", "2026-07-28T11:30:00Z", "recent"),
        _plan("2", "2026-07-28T07:00:00Z", "older"),
        _plan("3", "2026-07-20T12:00:00Z", "outside week"),
    ]
    windows = build_windows(plans, as_of="2026-07-28T12:00:00Z")
    counts = {item.hours: item.post_count for item in windows}

    assert counts[1] == 1
    assert counts[4] == 1
    assert counts[12] == 2
    assert counts[24] == 2
    assert counts[168] == 2


def test_openai_news_context_engine_returns_structured_reusable_state():
    session = FakeSession()
    plans = [
        _plan("1", "2026-07-28T11:30:00Z", "Threats against shipping increased."),
        _plan("2", "2026-07-28T07:00:00Z", "No closure has been confirmed."),
    ]

    result = OpenAINewsContextEngine(api_key="test", model="test-model", session=session).assess(
        plans,
        channel="example",
        as_of="2026-07-28T12:00:00Z",
    )

    assert result.regime_label == "sustained regional escalation"
    assert result.escalation_direction == "escalating"
    assert result.conflict_level == 0.8
    assert result.model == "test-model"
    assert result.source_post_count == 2
    assert result.coverage_warning
    assert len(result.windows) == 5
    assert "WINDOW 168 HOURS" in session.calls[0][1]["json"]["input"]
