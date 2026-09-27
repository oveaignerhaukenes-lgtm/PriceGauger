from contextlib import contextmanager
from dataclasses import asdict
from types import SimpleNamespace
import json

import pytest

import strategy_execution_open_v1 as opening
from strategy_execution_scope_v1 import ExecutionAdapterScopeV1


def _scope():
    return ExecutionAdapterScopeV1("gold:p1","gold","p1","h1","pilot","acct",123,
                                   "CfdOnFutures",2000,50)


def test_approved_plan_queues_exact_budget_and_product_with_no_broker_post(monkeypatch):
    scope = _scope()
    enrollment = SimpleNamespace(enabled=True,strategy_key="macd",account_id="acct",uic=123,
        asset_type="CfdOnFutures",live_open_armed=True,entry_mode=opening.ENTRY_MODE_APPROVAL_REQUIRED,
        pilot_key="pilot")
    calls = []
    monkeypatch.setattr(opening, "validate_strategy_execution_binding_v1", lambda **k:
        SimpleNamespace(scope=scope,execution_strategy_key="macd"))
    monkeypatch.setattr(opening, "assert_research_scope_v1", lambda **k:
        SimpleNamespace(payload_json=json.dumps({"direction":"LONG"})))
    monkeypatch.setattr(opening, "load_strategy_enrollment_v2", lambda k: enrollment)
    monkeypatch.setattr(opening, "code_gate_enabled_v2", lambda: True)
    monkeypatch.setattr(opening, "load_live_open_config_v2", lambda: SimpleNamespace(armed=True))
    monkeypatch.setattr(opening, "auto_manage_enabled_v1", lambda e: False)
    monkeypatch.setattr(opening, "position_management_enabled_v1", lambda e: True)
    monkeypatch.setattr(opening, "_pg_execution_inflight_v2", lambda e: False)
    @contextmanager
    def connection():
        yield SimpleNamespace(execute=lambda *a, **k: SimpleNamespace(fetchone=lambda: None))
    monkeypatch.setattr(opening, "connect", connection)
    monkeypatch.setattr(opening, "configured_client", lambda: SimpleNamespace(base_url=opening.LIVE_BASE_URL,
        _get=lambda *a, **k: {"InstrumentPriceDetails":{"IsMarketOpen":True},"Quote":{"ErrorCode":"None"}},
        _post=lambda *a, **k: (_ for _ in ()).throw(AssertionError("UI cannot POST to broker"))))
    monkeypatch.setattr(opening, "_account_info", lambda *a: ("key","NOK"))
    monkeypatch.setattr(opening, "load_pilot_equity_v2", lambda **k: SimpleNamespace(currency="NOK",entry_budget=5000))
    monkeypatch.setattr(opening, "_position_observations_v2", lambda c: ())
    monkeypatch.setattr(opening, "_exact_product_observation", lambda e,o: None)
    monkeypatch.setattr(opening, "_open_orders_exist", lambda *a, **k: False)
    monkeypatch.setattr(opening, "grant_user_confirmed_flat_authority_v2", lambda **k: calls.append(("flat",k)))
    monkeypatch.setattr(opening, "_persist_intent_and_request_v2", lambda **k:
        calls.append(("durable",k)) or True)
    monkeypatch.setattr(opening, "approve_open_request_v2", lambda **k: calls.append(("approve",k)))
    monkeypatch.setattr(opening, "mark_research_handoff_queued_v1", lambda p: calls.append(("queued",p)))
    result = opening.queue_strategy_lab_open_v1(**asdict(scope))
    durable = next(k for name,k in calls if name=="durable")
    assert durable["execution_scope"] == scope
    assert durable["budget_amount"] == 1000 and durable["budget_currency"] == "NOK"
    assert durable["state"].intent_signal == "STRATEGY_LAB_APPROVED_OPEN"
    assert any(name=="approve" and k["request_id"] == result.request_id for name,k in calls if name=="approve")


def test_crossed_scope_stops_before_flat_authority_or_order(monkeypatch):
    monkeypatch.setattr(opening, "validate_strategy_execution_binding_v1", lambda **k:
        (_ for _ in ()).throw(ValueError("EXECUTION_HANDOFF_IDENTITY_MISMATCH")))
    monkeypatch.setattr(opening, "grant_user_confirmed_flat_authority_v2", lambda **k:
        (_ for _ in ()).throw(AssertionError("crossed scope must not get authority")))
    with pytest.raises(ValueError, match="HANDOFF_IDENTITY_MISMATCH"):
        opening.queue_strategy_lab_open_v1(**{**asdict(_scope()),"handoff_id":"h2"})
