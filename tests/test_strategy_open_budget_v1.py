from contextlib import contextmanager
from dataclasses import asdict
from types import SimpleNamespace

import pytest

import autotrader_open_sizing_v2 as sizing
import autotrader_manage_control_v1 as manage
import autotrader_strategy_enrollment_v2 as enrollments
import strategy_execution_budget_v1 as budget
import strategy_execution_adapter_v1 as adapter
from strategy_execution_scope_v1 import ExecutionAdapterScopeV1, assert_adapter_scope_match_v1


def _scope():
    return ExecutionAdapterScopeV1("gold:p1", "gold", "p1", "h1", "pilot1", "acct", 123,
                                   "CfdOnFutures", 2000, 50)


def test_budget_change_is_an_identity_mismatch():
    original = _scope()
    modified = ExecutionAdapterScopeV1(**{**asdict(original), "exposure_pct": 75})
    with pytest.raises(ValueError, match="EXECUTION_ADAPTER_SCOPE_MISMATCH"):
        assert_adapter_scope_match_v1(original, modified)
    with pytest.raises(ValueError, match="finite"):
        ExecutionAdapterScopeV1(**{**asdict(original), "budget_nok": float("inf")})


def test_adapter_rejects_budget_not_in_approved_snapshot(monkeypatch):
    import json
    scope = _scope()
    snapshot = {**asdict(scope), "direction":"LONG"}
    monkeypatch.setattr(adapter, "assert_research_scope_v1", lambda **k:
        SimpleNamespace(handoff_id="h1",status="APPROVED",payload_json=json.dumps(snapshot)))
    monkeypatch.setattr(adapter, "load_strategy_enrollment_v2", lambda k:
        SimpleNamespace(enabled=True,execution_mode=adapter.EXECUTION_MODE_LIVE,
                        account_id="acct",uic=123,asset_type="CfdOnFutures",strategy_key="macd"))
    with pytest.raises(ValueError, match="HANDOFF_SNAPSHOT_MISMATCH"):
        adapter.validate_strategy_execution_binding_v1(**{**asdict(scope),"budget_nok":4000})


def test_fixed_entry_that_passes_saxo_precheck_still_respects_notional_cap(monkeypatch):
    rules = SimpleNamespace(increment_size=.01, amount_quantum=.01, amount_decimals=2)
    monkeypatch.setattr(sizing, "load_entry_instrument_rules_v2", lambda *a, **k: rules)
    monkeypatch.setattr(sizing, "resolve_minimum_entry_amount_v2", lambda *a, **k: SimpleNamespace(amount=.01))
    monkeypatch.setattr(sizing, "load_entry_sizing_policy_v2", lambda **k: SimpleNamespace(sizing_mode=sizing.SIZING_MODE_FIXED, fixed_amount=.01))
    monkeypatch.setattr(sizing, "_attempt_precheck", lambda *a, **k: SimpleNamespace(allowed=True, amount=.01, notional_account=2500))
    monkeypatch.setattr(sizing, "minimum_legal_amount_v2", lambda *a: .01)
    with pytest.raises(sizing.EntrySizingError, match="fixed amount does not pass"):
        sizing.find_largest_legal_entry_v2(None, account_key="key", account_currency="NOK",
            instrument=SimpleNamespace(uic=123, asset_type="CfdOnFutures"), direction="LONG",
            envelope=None, controlled_capital=1000, external_reference_prefix="test", max_notional_account=1000)


def test_strategy_lab_signal_without_provenance_cannot_fall_back_to_uncapped(monkeypatch):
    @contextmanager
    def connection():
        yield SimpleNamespace(execute=lambda *a: SimpleNamespace(fetchone=lambda: None))
    monkeypatch.setattr(budget, "ensure_strategy_open_provenance_schema_v1", lambda: None)
    monkeypatch.setattr(budget, "connect", connection)
    with pytest.raises(ValueError, match="PROVENANCE_MISSING"):
        budget.scoped_open_cap_v1({"request_id": "r1", "signal": "STRATEGY_LAB_APPROVED_OPEN"}, account_currency="NOK")


def test_scoped_status_reports_block_reason_and_confirmed_close(monkeypatch):
    import strategy_execution_control_v1 as controls
    rows = [{"status": "BLOCKED", "request_id": "r1", "block_reason": "MARKET_CLOSED"}]
    @contextmanager
    def connection():
        yield SimpleNamespace(execute=lambda *a: SimpleNamespace(fetchone=lambda: rows.pop(0)))
    monkeypatch.setattr(budget, "ensure_strategy_open_provenance_schema_v1", lambda: None)
    monkeypatch.setattr(controls, "ensure_strategy_execution_control_schema_v1", lambda: None)
    monkeypatch.setattr(budget, "connect", connection)
    assert budget.load_scoped_open_status_v1("gold:p1") == ("BLOCKED(ORDER): MARKET_CLOSED", "r1")
    rows.extend([{"status": "RECONCILED", "request_id": "r1", "block_reason": None}, {"control_id": "c1"}])
    assert budget.load_scoped_open_status_v1("gold:p1") == ("CLOSED", "r1")


def test_scoped_request_rejects_budget_mutation(monkeypatch):
    scope = _scope()
    provenance = {**asdict(scope), "max_notional_nok": 1000}
    @contextmanager
    def connection():
        yield SimpleNamespace(execute=lambda *a: SimpleNamespace(fetchone=lambda: provenance))
    monkeypatch.setattr(budget, "ensure_strategy_open_provenance_schema_v1", lambda: None)
    monkeypatch.setattr(budget, "connect", connection)
    monkeypatch.setattr(budget, "validate_strategy_execution_binding_v1", lambda **k: SimpleNamespace(scope=scope, execution_strategy_key="macd"))
    monkeypatch.setattr(enrollments, "load_strategy_enrollment_v2", lambda k: SimpleNamespace(strategy_key="macd"))
    monkeypatch.setattr(manage, "auto_manage_enabled_v1", lambda e: False)
    monkeypatch.setattr(manage, "position_management_enabled_v1", lambda e: True)
    request = {"request_id": "r1", "budget_currency": "NOK", "budget_amount": 1200,
               "signal": "STRATEGY_LAB_APPROVED_OPEN",
               "pilot_key": "pilot1", "strategy_key": "macd", "account_id": "acct",
               "uic": 123, "asset_type": "CfdOnFutures"}
    with pytest.raises(ValueError, match="PROVENANCE_MISMATCH"):
        budget.scoped_open_cap_v1(request, account_currency="NOK")
    request["budget_amount"] = 1000
    assert budget.scoped_open_cap_v1(request, account_currency="NOK") == 1000
