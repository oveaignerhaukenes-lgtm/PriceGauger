from __future__ import annotations

from pathlib import Path

import autotrader_closed_position_reconciliation_v2 as reconciliation_v2


def _attempt(event_id: str) -> dict[str, object]:
    return {"event_id": event_id}


def setup_function() -> None:
    reconciliation_v2._RECONCILIATION_RETRY_STATE.clear()
    reconciliation_v2._ORDER_FILL_POSITION_ID_CACHE.clear()
    reconciliation_v2._ACCOUNT_CONTEXT_CACHE = None


def test_reconciliation_processes_only_one_due_historical_close_per_cycle():
    attempts = (_attempt("old-1"), _attempt("old-2"), _attempt("old-3"))

    due = reconciliation_v2._due_attempts_v2(attempts, now_monotonic=100.0)

    assert [item["event_id"] for item in due] == ["old-1"]
    assert reconciliation_v2.MAX_RECONCILIATION_CANDIDATES_PER_CYCLE == 1


def test_failed_historical_close_backs_off_without_starving_next_candidate():
    attempts = (_attempt("old-1"), _attempt("old-2"))
    delay = reconciliation_v2._schedule_reconciliation_retry_v2(
        "old-1", now_monotonic=100.0
    )

    assert delay == 30
    assert [
        item["event_id"]
        for item in reconciliation_v2._due_attempts_v2(
            attempts, now_monotonic=110.0
        )
    ] == ["old-2"]
    assert [
        item["event_id"]
        for item in reconciliation_v2._due_attempts_v2(
            attempts, now_monotonic=131.0
        )
    ] == ["old-1"]


def test_reconciliation_backoff_escalates_and_caps():
    now = 100.0
    delays = []
    for _ in range(7):
        delays.append(
            reconciliation_v2._schedule_reconciliation_retry_v2(
                "event", now_monotonic=now
            )
        )
        now += 10_000.0

    assert delays == [30, 120, 600, 1800, 3600, 3600, 3600]


def test_account_context_is_cached_across_background_cycles(monkeypatch):
    calls = []

    def fake_load(client):
        calls.append(client)
        return {"ACC": {"account_key": "AK", "client_key": "CK", "currency": "NOK"}}

    monkeypatch.setattr(reconciliation_v2, "_account_contexts_v2", fake_load)
    monkeypatch.setattr(reconciliation_v2.time, "monotonic", lambda: 100.0)
    client = object()

    first = reconciliation_v2._cached_account_contexts_v2(client)
    second = reconciliation_v2._cached_account_contexts_v2(client)

    assert first == second
    assert calls == [client]


def test_accounting_runtime_has_a_calm_minimum_cadence_and_no_reversal_authority():
    source = Path("autotrader_closed_position_reconciliation_v2.py").read_text(encoding="utf-8")
    open_facade = Path("autotrader_live_open_v2.py").read_text(encoding="utf-8")

    assert "MIN_RECONCILIATION_INTERVAL_SECONDS = 15" in source
    assert "MAX_RECONCILIATION_CANDIDATES_PER_CYCLE = 1" in source
    assert "never sits on the critical CLOSE -> confirmed FLAT -> OPEN reversal path" in source
    assert "P/L reconciliation is accounting" in open_facade
    assert "status IN ('SUBMITTING', 'UNCERTAIN')" in open_facade
    assert "status IN ('ORDER_ACCEPTED', 'RECONCILED')" in open_facade
