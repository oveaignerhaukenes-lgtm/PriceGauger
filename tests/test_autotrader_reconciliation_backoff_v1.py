from __future__ import annotations

import autotrader_closed_position_reconciliation_v2 as reconciliation_v2


def setup_function():
    reconciliation_v2._RECONCILIATION_RETRY_STATE.clear()


def test_retry_backoff_increases_and_caps():
    event = "event-1"
    delays = [
        reconciliation_v2._schedule_reconciliation_retry_v2(event, now_monotonic=float(i))
        for i in range(6)
    ]
    assert delays == [30, 120, 600, 1800, 3600, 3600]


def test_due_attempts_skip_deferred_and_process_only_one_candidate():
    attempts = (
        {"event_id": "oldest"},
        {"event_id": "next"},
        {"event_id": "third"},
    )
    reconciliation_v2._RECONCILIATION_RETRY_STATE["oldest"] = (1, 200.0)

    due = reconciliation_v2._due_attempts_v2(attempts, now_monotonic=100.0)
    assert due == ({"event_id": "next"},)


def test_due_attempt_becomes_eligible_after_backoff():
    attempt = {"event_id": "event-1"}
    reconciliation_v2._RECONCILIATION_RETRY_STATE["event-1"] = (1, 130.0)

    assert reconciliation_v2._due_attempts_v2((attempt,), now_monotonic=129.0) == ()
    assert reconciliation_v2._due_attempts_v2((attempt,), now_monotonic=130.0) == (attempt,)


def test_success_clear_removes_retry_state():
    reconciliation_v2._RECONCILIATION_RETRY_STATE["event-1"] = (4, 999.0)
    reconciliation_v2._clear_reconciliation_retry_v2("event-1")
    assert "event-1" not in reconciliation_v2._RECONCILIATION_RETRY_STATE


def test_accounting_cadence_is_deliberately_slower_than_execution():
    assert reconciliation_v2.MIN_RECONCILIATION_INTERVAL_SECONDS >= 15
    assert reconciliation_v2.MAX_RECONCILIATION_CANDIDATES_PER_CYCLE == 1
