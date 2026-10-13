from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from autotrader_v3_order_guard_v1 import ensure_schema, claim_reserved_for_submission_v3
from autotrader_v3_operator_order_recovery_v1 import (
    OrderRecoveryDeniedV3, recovery_eligibility_v3, recover_stale_reserved_v3,
)


STAMP = "2026-10-13 01:58:58+00:00"
NOW = datetime(2026, 10, 13, 10, 30, tzinfo=timezone.utc)


def pending(state="RESERVED"):
    return {
        "request_key": "test-order-1",
        "state": state,
        "broker_order_id": None,
        "updated_at": STAMP,
        "submitted_amount": 0.01,
        "submitted_side": "Buy",
        "expected_inventory": -0.01,
    }


def test_eligibility_only_stale_unsubmitted_reserved_with_exact_pre_inventory():
    assert recovery_eligibility_v3(pending=pending(), actual=-0.02, now=NOW)[0]
    assert not recovery_eligibility_v3(pending=pending("SUBMITTING"), actual=-0.02, now=NOW)[0]
    assert not recovery_eligibility_v3(pending=pending("UNKNOWN"), actual=-0.02, now=NOW)[0]
    assert not recovery_eligibility_v3(pending=pending(), actual=-0.01, now=NOW)[0]
    recent=pending()
    recent["updated_at"]="2026-10-13 10:29:00+00:00"
    assert not recovery_eligibility_v3(pending=recent, actual=-0.02, now=NOW)[0]
    with_broker=pending()
    with_broker["broker_order_id"]="123"
    assert not recovery_eligibility_v3(pending=with_broker, actual=-0.02, now=NOW)[0]


class FakeBroker:
    def __init__(self, working=None, inventory=-0.02):
        self.client=self
        self.working=working or []
        self.inventory=inventory
        self.calls=[]

    def _account_context_exact(self, account_id):
        assert account_id=="acct-C"
        return "account-key-C", "client-C"

    def signed_inventory_exact(self, **kwargs):
        self.calls.append(("inventory", kwargs))
        return self.inventory

    def _get(self, path, params=None):
        self.calls.append(("get", path))
        assert path=="port/v1/orders/me"
        return {"Data":list(self.working)}

    def place_order(self, *args, **kwargs):
        raise AssertionError("recovery must never place a broker order")


def setup_reservation(monkeypatch, tmp_path):
    import autotrader_v3_operator_order_recovery_v1 as recovery
    db_path=str(tmp_path / "v3-recovery.sqlite")
    ensure_schema(db_path)
    from database import connect
    with connect(db_path) as db:
        db.execute("""INSERT INTO autotrader_v3_order_guard(
          request_key,trader_id,account_id,uic,asset_type,state,expected_inventory,
          submitted_amount,submitted_side,updated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?)""",
          ("test-order-1", "trader-C", "acct-C", 4912, "CfdOnIndex", "RESERVED",
           -0.01, 0.01, "Buy", STAMP))
    monkeypatch.setattr(recovery,"load_v3_instances_v1",lambda **kwargs:(
        SimpleNamespace(instance_id="trader-C",account_id="acct-C",uic=4912,asset_type="CfdOnIndex"),))
    monkeypatch.setattr(recovery,"pending_order_v3",lambda **kwargs: pending())
    return db_path


def test_verified_operator_recovery_is_atomic_and_nontrading(monkeypatch,tmp_path):
    db_path=setup_reservation(monkeypatch,tmp_path)
    broker=FakeBroker()
    result=recover_stale_reserved_v3(instance_id="trader-C",request_key="test-order-1",
        db_path=db_path,broker=broker,now=NOW)
    assert "Ingen ordre sendt" in result
    from database import connect
    with connect(db_path) as db:
        row=db.execute("SELECT state,detail FROM autotrader_v3_order_guard WHERE request_key=?",("test-order-1",)).fetchone()
    assert row[0]=="REJECTED"
    assert "OPERATOR_RECOVERED_PRE_SUBMIT_RESERVED" in row[1]
    assert broker.calls.count(("get", "port/v1/orders/me"))==1
    assert sum(x[0]=="inventory" for x in broker.calls)==2
    # Worker must never regain submission authority for the now-retired request.
    assert not claim_reserved_for_submission_v3(request_key="test-order-1",db_path=db_path)


@pytest.mark.parametrize("working,inventory",[
    ([{"AccountId":"acct-C","OrderId":"active"}],-0.02),
    ([{"OrderId":"identity-missing"}],-0.02),
    ([], -0.01),
])
def test_recovery_fails_closed_without_mutating_reservation(monkeypatch,tmp_path,working,inventory):
    db_path=setup_reservation(monkeypatch,tmp_path)
    broker=FakeBroker(working=working,inventory=inventory)
    with pytest.raises(OrderRecoveryDeniedV3):
        recover_stale_reserved_v3(instance_id="trader-C",request_key="test-order-1",
            db_path=db_path,broker=broker,now=NOW)
    from database import connect
    with connect(db_path) as db:
        row=db.execute("SELECT state FROM autotrader_v3_order_guard WHERE request_key=?",("test-order-1",)).fetchone()
    assert row[0]=="RESERVED"


def test_order_claim_is_one_shot_and_reset_widget_is_one_click():
    widget=Path("autotrader_status_widget_v1.py").read_text(encoding="utf-8")
    runtime=Path("autotrader_v3_live_runtime_v1.py").read_text(encoding="utf-8")
    assert "data-key=" in widget and "Reset ordre" in widget
    assert 'recovery-pin' not in widget
    assert 'PG_V3_ORDER_RECOVERY_PIN' not in widget
    assert "on_recovery_request_change=" in widget
    assert "recover_stale_reserved_v3" in widget
    assert "claim_reserved_for_submission_v3(request_key=request_key" in runtime
    assert "mark_order_v3(request_key=request_key,state='SUBMITTING'" not in runtime
    assert "place_order(" not in widget
