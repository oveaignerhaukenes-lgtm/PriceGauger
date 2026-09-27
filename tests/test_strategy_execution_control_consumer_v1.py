from contextlib import contextmanager
from types import SimpleNamespace

import strategy_execution_control_consumer_v1 as consumer


def test_unbound_control_is_rejected_without_any_close(monkeypatch):
    control = {"control_id":"c1", "status":"PENDING", "action":"CLOSE",
               "scope_id":"gold:p1", "plan_id":"p1", "strategy_key":"gold"}
    @contextmanager
    def connection():
        def execute(sql, args=()):
            if "SELECT * FROM pg_v2_strategy_execution_controls" in sql:
                return SimpleNamespace(fetchall=lambda: [control])
            if "FROM pg_v2_strategy_open_provenance" in sql:
                assert args == ("gold:p1", "p1", "gold")
                return SimpleNamespace(fetchone=lambda: None)
            raise AssertionError(sql)
        yield SimpleNamespace(execute=execute)
    statuses = []
    monkeypatch.setattr(consumer, "using_postgres", lambda: True)
    monkeypatch.setattr(consumer, "ensure_strategy_execution_control_schema_v1", lambda: None)
    monkeypatch.setattr(consumer, "ensure_strategy_open_provenance_schema_v1", lambda: None)
    monkeypatch.setattr(consumer, "connect", connection)
    monkeypatch.setattr(consumer, "_set_status", lambda *a, **k: statuses.append((a,k)))
    monkeypatch.setattr(consumer, "request_manual_close_v1", lambda *a, **k: (_ for _ in ()).throw(AssertionError("CLOSE must not be called")))
    assert consumer.consume_strategy_execution_controls_v1(observations=()) == 1
    assert statuses == [(('c1',), {'status':'REJECTED','reason':'NO_EXECUTED_OPEN_IN_THIS_SCOPE'})]


def test_scoped_close_requires_exact_reconciled_position_amount(monkeypatch):
    control = {"control_id":"00000000-0000-0000-0000-000000000001", "status":"PENDING",
               "action":"CLOSE", "scope_id":"gold:p1", "plan_id":"p1", "strategy_key":"gold"}
    source = {"request_id":"r1", "pilot_key":"pilot", "execution_strategy_key":"macd",
              "account_id":"acct", "uic":123, "asset_type":"CfdOnFutures", "budget_amount":1000,
              "budget_currency":"NOK", "signal":"STRATEGY_LAB_APPROVED_OPEN",
              "open_status":"RECONCILED", "open_amount":.01}
    @contextmanager
    def connection():
        def execute(sql, args=()):
            if "SELECT * FROM pg_v2_strategy_execution_controls" in sql:
                return SimpleNamespace(fetchall=lambda: [control])
            if "FROM pg_v2_strategy_open_provenance" in sql:
                assert args == ("gold:p1", "p1", "gold")
                return SimpleNamespace(fetchone=lambda: source)
            if "WHERE request_id=? AND pilot_key=?" in sql:
                return SimpleNamespace(fetchone=lambda: None)
            raise AssertionError(sql)
        yield SimpleNamespace(execute=execute)
    monkeypatch.setattr(consumer, "using_postgres", lambda: True)
    monkeypatch.setattr(consumer, "ensure_strategy_execution_control_schema_v1", lambda: None)
    monkeypatch.setattr(consumer, "ensure_strategy_open_provenance_schema_v1", lambda: None)
    monkeypatch.setattr(consumer, "connect", connection)
    monkeypatch.setattr(consumer, "scoped_open_cap_v1", lambda *a, **k: 1000)
    monkeypatch.setattr(consumer, "load_strategy_enrollment_v2", lambda *a: SimpleNamespace(
        pilot_key="pilot", strategy_key="macd", anchor_net_position_id="pos"))
    monkeypatch.setattr(consumer, "_exact_product_observation", lambda *a: SimpleNamespace(
        net_position_id="pos", amount=.02))
    monkeypatch.setattr(consumer, "is_position_managed_v1", lambda *a: True)
    statuses = []
    monkeypatch.setattr(consumer, "_set_status", lambda *a, **k: statuses.append((a,k)))
    monkeypatch.setattr(consumer, "request_manual_close_v1", lambda *a, **k: (_ for _ in ()).throw(AssertionError("wrong position size must not close")))
    assert consumer.consume_strategy_execution_controls_v1(observations=()) == 1
    assert statuses == [((control['control_id'],), {'status':'REJECTED','reason':'SCOPED_POSITION_BASIS_CHANGED'})]
