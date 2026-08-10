from __future__ import annotations

from datetime import datetime, timezone

import market_chat


class _Response:
    status_code = 200
    text = ""

    def raise_for_status(self):
        return None

    def json(self):
        return {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "Grounded answer"}],
                }
            ]
        }


def test_sample_points_preserves_first_last_and_bounds_size():
    points = tuple((f"2026-08-10T00:{index:02d}:00+00:00", float(index)) for index in range(60))

    sampled = market_chat._sample_points(points, limit=10)

    assert len(sampled) == 10
    assert sampled[0]["price"] == 0.0
    assert sampled[-1]["price"] == 59.0


def test_learning_summary_uses_complete_scored_outcomes():
    class Outcome:
        def __init__(self, status, direction_hit, interval_hit, realized_move_pct):
            self.status = status
            self.direction_hit = direction_hit
            self.interval_hit = interval_hit
            self.realized_move_pct = realized_move_pct

    summary = market_chat._learning_summary(
        [
            Outcome("COMPLETE", True, True, 1.0),
            Outcome("COMPLETE", False, True, -0.5),
            Outcome("PARTIAL", True, False, 9.0),
        ]
    )

    assert summary["complete_forecasts"] == 2
    assert summary["direction_hit_rate"] == 0.5
    assert summary["interval_hit_rate"] == 1.0
    assert summary["mean_realized_move_pct"] == 0.25


def test_answer_market_chat_refreshes_context_and_disables_api_storage(monkeypatch):
    captured = {}
    context = {
        "context_version": "test",
        "generated_at": datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc).isoformat(),
        "market": "Silver",
        "canonical_price_history": [{"at": "now", "price": 81.2}],
    }

    monkeypatch.setattr(market_chat, "build_market_chat_context", lambda market, db_path="pricegauger.db": context)

    def fake_post(url, *, headers, json, timeout):
        captured.update({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return _Response()

    monkeypatch.setattr(market_chat.requests, "post", fake_post)

    answer = market_chat.answer_market_chat(
        "Silver",
        [
            {"role": "user", "content": "Hva ser du?"},
            {"role": "assistant", "content": "Tidligere svar"},
            {"role": "user", "content": "Og nå?"},
        ],
        api_key="secret-key",
        model="test-model",
    )

    assert answer == "Grounded answer"
    assert captured["url"] == market_chat.OPENAI_RESPONSES_URL
    assert captured["json"]["store"] is False
    assert captured["json"]["model"] == "test-model"
    assert captured["json"]["input"][-1]["content"] == "Og nå?"
    assert "Silver" in captured["json"]["instructions"]
    assert "authoritative" in captured["json"]["instructions"].lower()
