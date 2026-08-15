from __future__ import annotations

from types import SimpleNamespace

import pytest

from analyst_companion_v2 import build_companion_payload_v2, derive_level_candidates_v2, validate_companion_analysis_v2
from companion_runtime_v2 import CompanionSessionV2, ask_companion_v2, refresh_companion_session_v2


def _view(*, market: str = "Gold", as_of: str = "2026-08-15T21:30:00+00:00"):
    history = tuple(
        (f"2026-08-15T21:{minute:02d}:00+00:00", price)
        for minute, price in enumerate(
            [100.0, 100.4, 100.1, 100.6, 100.2, 100.7, 100.3, 100.8, 100.4, 100.65, 100.5, 100.75]
        )
    )
    return SimpleNamespace(
        market=market,
        as_of=as_of,
        direction="BULLISH",
        expected_return=0.004,
        lower_return=-0.002,
        upper_return=0.010,
        confidence=0.72,
        path_shape="TREND_CONTINUATION",
        trend_state="BULLISH",
        momentum_state="BULLISH",
        volatility_state="NORMAL",
        structure_state="HH_HL",
        technical_score=0.44,
        horizon_seconds=900,
        price_history=history,
    )


def _record(payload):
    supports = [item["level_id"] for item in payload["level_candidates"] if item["kind"] == "SUPPORT"]
    resistances = [item["level_id"] for item in payload["level_candidates"] if item["kind"] == "RESISTANCE"]
    return {
        "directional_context": "BULLISH",
        "breakout_status": "TESTING",
        "pullback_type": "NORMAL",
        "squeeze_risk": "MODERATE",
        "watched_support_ids": supports[:1],
        "watched_resistance_ids": resistances[:1],
        "confidence": 0.68,
        "what_changed": "Momentum remains constructive near resistance.",
        "commentary": "Price is testing a system-derived resistance candidate while the Technical Core remains bullish.",
        "watch_conditions": ["Watch whether the resistance test is accepted or rejected."],
    }


class FakeProvider:
    def __init__(self):
        self.analysis_calls = 0
        self.answer_calls = 0

    def analyze(self, payload):
        self.analysis_calls += 1
        return _record(payload)

    def answer(self, payload, question):
        self.answer_calls += 1
        return {"answer": "The supplied state still looks like a normal pullback, not confirmed reversal evidence.", "confidence": 0.66}


def test_level_candidates_are_derived_from_observed_history_and_have_stable_ids():
    levels = derive_level_candidates_v2(_view().price_history)

    assert levels
    assert all(level.level_id.startswith(("S", "R")) for level in levels)
    assert all(level.kind in {"SUPPORT", "RESISTANCE"} for level in levels)
    assert all(level.touches >= 1 for level in levels)


def test_analysis_may_reference_only_system_derived_level_ids():
    payload = build_companion_payload_v2(_view())
    record = _record(payload)
    record["watched_resistance_ids"] = ["R999"]

    with pytest.raises(ValueError, match="unknown or wrong-kind"):
        validate_companion_analysis_v2(payload, record)


def test_session_refreshes_only_when_snapshot_changes_and_carries_previous_analysis():
    provider = FakeProvider()
    session = CompanionSessionV2.activate("Gold")
    first = _view()

    assert refresh_companion_session_v2(session, view=first, provider=provider) is True
    assert provider.analysis_calls == 1
    assert session.analysis is not None
    assert refresh_companion_session_v2(session, view=first, provider=provider) is False
    assert provider.analysis_calls == 1

    second = _view(as_of="2026-08-15T21:31:00+00:00")
    assert refresh_companion_session_v2(session, view=second, provider=provider) is True
    assert provider.analysis_calls == 2
    assert session.last_snapshot_as_of == second.as_of


def test_session_is_market_bound_and_has_no_execution_surface():
    provider = FakeProvider()
    session = CompanionSessionV2.activate("Gold")

    with pytest.raises(ValueError, match="bound to one market"):
        refresh_companion_session_v2(session, view=_view(market="Silver"), provider=provider)

    assert not hasattr(session, "buy")
    assert not hasattr(session, "sell")
    assert not hasattr(session, "execute")


def test_ask_companion_uses_active_session_context_without_mutating_analysis():
    provider = FakeProvider()
    session = CompanionSessionV2.activate("Gold")
    view = _view()
    refresh_companion_session_v2(session, view=view, provider=provider)
    previous = session.analysis

    answer, confidence = ask_companion_v2(
        session,
        view=view,
        provider=provider,
        question="Normal pullback or reversal risk?",
    )

    assert "normal pullback" in answer
    assert confidence == pytest.approx(0.66)
    assert provider.answer_calls == 1
    assert session.analysis is previous
    assert [turn.kind for turn in session.turns[-2:]] == ["question", "answer"]
