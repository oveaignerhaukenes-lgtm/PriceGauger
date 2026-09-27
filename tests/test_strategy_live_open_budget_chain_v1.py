"""Canonical worker must check scoped notional after its final Saxo precheck."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import autotrader_live_open_legacy_v2 as worker
import autotrader_execution_guard_v1 as guard
import time


def _worker_with_capped_request(monkeypatch, *, final_notional, budget_cap):
    # Other tests may import the guarded public facade during collection. Skip
    # its unrelated timed working-order sweep; this test exercises the original
    # canonical cycle's budget/precheck/submit edges.
    monkeypatch.setattr(guard, "_LAST_SWEEP", time.monotonic())
    now = datetime.now(timezone.utc)
    request = {"request_id":"00000000-0000-0000-0000-000000000001", "pilot_key":"pilot",
        "strategy_key":"macd", "desired_direction":"LONG", "signal_at":now,
        "signal":"STRATEGY_LAB_APPROVED_OPEN", "account_id":"acct", "uic":123,
        "asset_type":"CfdOnFutures", "market_id":1, "instrument_id":1,
        "budget_amount":budget_cap, "budget_currency":"NOK", "status":"PENDING", "created_at":now}
    enrollment = SimpleNamespace(enabled=True, execution_mode=worker.EXECUTION_MODE_LIVE,
        strategy_key="macd", account_id="acct", uic=123, asset_type="CfdOnFutures",
        market_id=1, instrument_id=1, entry_mode=worker.ENTRY_MODE_AUTO,
        live_open_armed=True, pilot_key="pilot", market_name="Gold")
    events = []
    monkeypatch.setattr(worker, "using_postgres", lambda: True)
    monkeypatch.setattr(worker, "ensure_autotrader_schema_v2", lambda: None)
    monkeypatch.setattr(worker, "load_live_open_config_v2", lambda: SimpleNamespace(armed=True))
    monkeypatch.setattr(worker, "code_gate_enabled_v2", lambda: True)
    monkeypatch.setattr(worker, "_candidate_open_requests", lambda: (request,))
    monkeypatch.setattr(worker, "_accepted_attempts", lambda: ())
    monkeypatch.setattr(worker, "_require_live_client", lambda: object())
    monkeypatch.setattr(worker, "_position_netting_mode", lambda c: "Intraday")
    monkeypatch.setattr(worker, "_position_observations_v2", lambda c: ())
    monkeypatch.setattr(worker, "load_strategy_enrollment_v2", lambda k: enrollment)
    monkeypatch.setattr(worker, "_entry_authority_changed_after_request", lambda r: False)
    monkeypatch.setattr(worker, "_newer_strategy_request_exists", lambda r: False)
    monkeypatch.setattr(worker, "_settled_close_provenance", lambda k: (True, False))
    monkeypatch.setattr(worker, "_product_positions", lambda *a, **k: ())
    monkeypatch.setattr(worker, "_account_info", lambda *a: ("key", "NOK"))
    monkeypatch.setattr(worker, "_open_orders_exist", lambda *a, **k: False)
    monkeypatch.setattr(worker, "load_pilot_equity_v2", lambda **k: SimpleNamespace(entry_budget=5000,currency="NOK"))
    monkeypatch.setattr(worker, "require_entry_policy_v2", lambda *a, **k: (None,None,None))
    monkeypatch.setattr(worker, "scoped_open_cap_v1", lambda *a, **k: budget_cap)
    monkeypatch.setattr(worker, "find_largest_legal_entry_v2", lambda *a, **k: (
        events.append(("sizing_cap",k["max_notional_account"],k["controlled_capital"]))
        or SimpleNamespace(amount=.01,rules=object())))
    monkeypatch.setattr(worker, "precheck_entry_amount_v2", lambda *a, **k:
        SimpleNamespace(allowed=True,notional_account=final_notional,buy_sell="Buy"))
    monkeypatch.setattr(worker, "_submit_authority_still_current", lambda r: True)
    monkeypatch.setattr(worker, "_record_attempt_before_submit", lambda **k: events.append(("durable",)) or True)
    monkeypatch.setattr(worker, "_update_request", lambda *a, **k: events.append(("status",k["status"],k.get("block_reason"))))
    monkeypatch.setattr(worker, "live_open_order_payload_v2", lambda **k: {"Amount":k["amount"]})
    monkeypatch.setattr(worker, "_post_once", lambda *a, **k: events.append(("broker_post",a[1])) or {"OrderId":"broker123"})
    monkeypatch.setattr(worker, "_update_attempt", lambda *a, **k: None)
    return events


def test_precheck_above_immutable_plan_cap_never_reaches_broker(monkeypatch):
    events = _worker_with_capped_request(monkeypatch,final_notional=1000.01,budget_cap=1000)
    result = worker.run_live_open_cycle_v2()
    assert ("sizing_cap", 1000, 1000) in events
    assert ("status", "BLOCKED", "STRATEGY_LAB_NOTIONAL_CAP_EXCEEDED") in events
    assert not any(event[0] in {"durable","broker_post"} for event in events)
    assert result.submitted == 0


def test_precheck_under_cap_uses_existing_durable_broker_path(monkeypatch):
    events = _worker_with_capped_request(monkeypatch,final_notional=980,budget_cap=1000)
    result = worker.run_live_open_cycle_v2()
    assert ("durable",) in events
    assert ("broker_post", "trade/v2/orders") in events
    assert result.submitted == 1
