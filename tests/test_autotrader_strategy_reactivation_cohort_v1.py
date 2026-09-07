from __future__ import annotations

from uuid import UUID

import autotrader_strategy_switch_v2 as switch


def test_first_strategy_activation_keeps_canonical_pilot(monkeypatch) -> None:
    monkeypatch.setattr(switch, "_pilot_history_exists_v2", lambda _pilot_key: False)
    result = switch._target_activation_pilot_key_v2(
        canonical_pilot_key="canonical-pilot",
        event_id="event-1",
    )
    assert result == "canonical-pilot"


def test_revisited_strategy_gets_fresh_activation_cohort(monkeypatch) -> None:
    seen = []

    def _history(pilot_key: str) -> bool:
        seen.append(pilot_key)
        return pilot_key == "canonical-pilot"

    monkeypatch.setattr(switch, "_pilot_history_exists_v2", _history)
    result = switch._target_activation_pilot_key_v2(
        canonical_pilot_key="canonical-pilot",
        event_id="event-2",
    )
    assert result != "canonical-pilot"
    UUID(result)
    assert seen[0] == "canonical-pilot"
    assert seen[-1] == result


def test_strategy_switch_no_longer_resumes_or_mutates_historical_cohort() -> None:
    source = open("autotrader_strategy_switch_v2.py", encoding="utf-8").read()
    assert "target strategy pilot already has history" not in source
    assert "strategy-activation" in source
    assert "canonical_target_pilot_key" in source
    assert "float(source_equity.equity)" in source
    assert "UPDATE pg_v2_autotrader_pilot_equity_state" not in source
    assert "DELETE FROM pg_v2_autotrader_pilot_equity_events" not in source
