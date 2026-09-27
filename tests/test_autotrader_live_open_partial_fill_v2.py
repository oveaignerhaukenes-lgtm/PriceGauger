from contextlib import contextmanager
from types import SimpleNamespace

import autotrader_live_open_legacy_v2 as worker


def _attempt():
    return {
        "request_id": "00000000-0000-0000-0000-000000000001",
        "account_id": "acct",
        "uic": 123,
        "asset_type": "CfdOnFutures",
        "desired_direction": "LONG",
        "amount": 2.0,
        "filled_amount": None,
        "order_id": "order-1",
    }


def _observation(amount=1.0):
    return SimpleNamespace(
        account_id="acct",
        uic=123,
        asset_type="CfdOnFutures",
        direction="Buy",
        amount=amount,
        net_position_id="pos-1",
    )


def test_partial_fill_waits_while_remainder_is_working(monkeypatch):
    monkeypatch.setattr(worker, "_accepted_attempts", lambda: (_attempt(),))
    monkeypatch.setattr(worker, "_position_observations_v2", lambda client: (_observation(),))
    monkeypatch.setattr(worker, "_account_info", lambda *a: ("key", "NOK"))
    monkeypatch.setattr(worker, "_open_orders_exist", lambda *a, **k: True)
    monkeypatch.setattr(worker, "_rotate_managed_basis_and_anchor", lambda *a: (_ for _ in ()).throw(
        AssertionError("transient partial fill must not be adopted")))
    assert worker.reconcile_live_open_attempts_v2(object()) == 0


def test_completed_partial_fill_becomes_durable_managed_basis(monkeypatch):
    writes = []
    monkeypatch.setattr(worker, "_accepted_attempts", lambda: (_attempt(),))
    monkeypatch.setattr(worker, "_position_observations_v2", lambda client: (_observation(),))
    monkeypatch.setattr(worker, "_account_info", lambda *a: ("key", "NOK"))
    monkeypatch.setattr(worker, "_open_orders_exist", lambda *a, **k: False)
    monkeypatch.setattr(worker, "_rotate_managed_basis_and_anchor", lambda request_id, observation:
        writes.append(("adopt", request_id, observation.amount)))
    @contextmanager
    def connection():
        yield SimpleNamespace(execute=lambda sql, args=(): writes.append(("db", sql, args)))
    monkeypatch.setattr(worker, "connect", connection)
    monkeypatch.setattr(worker, "_update_attempt", lambda request_id, **k:
        writes.append(("attempt", request_id, k["status"])))
    monkeypatch.setattr(worker, "_update_request", lambda request_id, **k:
        writes.append(("request", request_id, k["status"])))

    assert worker.reconcile_live_open_attempts_v2(object()) == 1
    assert any(item[0] == "db" and item[2][0] == 1.0 for item in writes)
    assert ("attempt", _attempt()["request_id"], worker.STATUS_RECONCILED) in writes
    assert ("request", _attempt()["request_id"], worker.STATUS_RECONCILED) in writes


def test_overfill_is_never_silently_adopted(monkeypatch):
    monkeypatch.setattr(worker, "_accepted_attempts", lambda: (_attempt(),))
    monkeypatch.setattr(worker, "_position_observations_v2", lambda client: (_observation(2.5),))
    monkeypatch.setattr(worker, "_rotate_managed_basis_and_anchor", lambda *a: (_ for _ in ()).throw(
        AssertionError("overfill requires explicit anomaly handling")))
    assert worker.reconcile_live_open_attempts_v2(object()) == 0
