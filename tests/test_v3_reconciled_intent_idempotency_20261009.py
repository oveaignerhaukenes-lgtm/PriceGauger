"""V3 LIVE must never replay a durable broker intent for a repeated closed bar."""
from pathlib import Path

from autotrader_v3_order_guard_v1 import (
    mark,
    order_state,
    pending_order,
    reserve,
)


def _scope(db, account="a"):
    return dict(
        trader_id="v3-5m",
        account_id=account,
        uic=4912,
        asset_type="CfdOnIndex",
        db_path=str(db),
    )


def test_successful_reconciled_key_does_not_reinsert_or_erase_evidence(tmp_path):
    db = tmp_path / "orders.sqlite"
    kw = _scope(db)
    assert reserve(request_key="same-closed-bar", **kw) is True
    mark(
        request_key="same-closed-bar", state="SUBMITTED",
        broker_order_id="saxo-123", db_path=str(db),
    )
    mark(request_key="same-closed-bar", state="RECONCILED", db_path=str(db))
    assert reserve(request_key="same-closed-bar", idempotent=True, **kw) is False
    assert order_state(request_key="same-closed-bar", db_path=str(db)) == "RECONCILED"
    assert pending_order(account_id="a", uic=4912, asset_type="CfdOnIndex", db_path=str(db)) is None


def test_pending_exact_boundary_conflict_fails_closed_without_new_record(tmp_path):
    db = tmp_path / "orders.sqlite"
    kw = _scope(db)
    assert reserve(request_key="already-pending", **kw) is True
    assert reserve(request_key="different-key", idempotent=True, **kw) is False
    pending = pending_order(account_id="a", uic=4912, asset_type="CfdOnIndex", db_path=str(db))
    assert pending["request_key"] == "already-pending"
    assert order_state(request_key="different-key", db_path=str(db)) is None


def test_separate_accounts_still_independently_reserve(tmp_path):
    db = tmp_path / "orders.sqlite"
    assert reserve(request_key="acct-a", idempotent=True, **_scope(db, "a")) is True
    assert reserve(request_key="acct-b", idempotent=True, **_scope(db, "b")) is True


def test_runtime_gates_reconciled_and_concurrent_conflicts_before_saxo():
    source = Path("autotrader_v3_live_runtime_v1.py").read_text(encoding="utf-8")
    replay = source.index("if prior_state=='RECONCILED':")
    reservation = source.index("inserted=reserve_order_v3(")
    collision = source.index("if not inserted:")
    submit = source.index("broker.place_order(order,confirm_live=True)")
    assert replay < reservation < collision < submit
    assert "idempotent=True" in source[reservation:collision]
    assert "continue" in source[replay:reservation]
    assert "continue" in source[collision:submit]
    assert "competing=pending_order_v3(" in source[collision:submit]
    assert "stopping before Saxo submission" in source
