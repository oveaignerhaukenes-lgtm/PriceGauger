"""P0 emergency recovery: deterministic SQLite + fake Saxo, never LIVE."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3

import pytest

import autotrader_v3_account_emergency_v1 as em

NOW = datetime.now(timezone.utc) + timedelta(minutes=10)  # deterministic simulated aged intents


class FakeClient:
    def __init__(self, broker):
        self.broker = broker
        self.calls = []

    def _get(self, path, params=None):
        self.calls.append(path)
        if self.broker.error is not None:
            raise self.broker.error
        if path == "port/v1/orders/me":
            return {"Data": list(self.broker.orders)}
        if path == "port/v1/positions":
            if not self.broker.position:
                return {"Data": []}
            return {"Data": [{
                "PositionId": "position1",
                "PositionBase": {"AccountId": "account-A", "Uic": 4912,
                                 "AssetType": "CfdOnIndex", "Amount": .01,
                                 "OpeningDirection": "Sell", "Status": "Open"}
            }]}
        if path == "port/v1/netpositions":
            if not self.broker.position:
                return {"Data": []}
            return {"Data": [{
                "NetPositionBase": {"AccountId": "account-A", "Uic": 4912,
                                    "AssetType": "CfdOnIndex",
                                    "AmountShort": .01, "AmountLong": 0}
            }]}
        if path == "cs/v1/audit/orderactivities":
            return {"Data": list(self.broker.activities)}
        raise AssertionError(path)


class FakeBroker:
    def __init__(self, *, position=True, error=None):
        self.position = position
        self.error = error
        self.orders = []
        self.activities = []
        self.client = FakeClient(self)
        self.sent = []

    def _account_context_exact(self, account_id):
        assert account_id == "account-A"
        return "key-A", "client-A"

    def place_order(self, order, *, confirm_live=False):
        assert confirm_live
        assert order.amount == .01
        assert order.buy_sell == "Buy"
        assert order.instrument.uic == 4912
        assert order.external_reference.startswith("pgv3-")
        assert order.payload()["ManualOrder"] is False
        self.sent.append(order)
        self.position = False
        self.activities.append({
            "AccountId": "account-A", "OrderId": "saxo-1",
            "ExternalReference": order.external_reference,
            "Status": "FinalFill", "SubStatus": "Confirmed",
        })
        return {"OrderId": "saxo-1"}


def prepare(tmp_path, *, state=None, position=True):
    db = str(tmp_path / "emergency.sqlite")
    em.activate_emergency_v1("account-A", "TEST", db_path=db, now=NOW)
    if state:
        from autotrader_v3_order_guard_v1 import reserve, mark
        reserve(request_key="known", trader_id="trader-A",
                account_id="account-A", uic=4912, asset_type="CfdOnIndex",
                expected_inventory=0, submitted_amount=.01,
                submitted_side="Buy", db_path=db)
        mark(request_key="known",state=state,db_path=db)
    return db, FakeBroker(position=position)


def test_unknown_quarantine_threshold():
    p = {"state": "UNKNOWN", "updated_at": (NOW-timedelta(seconds=16)).isoformat()}
    assert em.should_start_emergency_v1(p,now=NOW)
    p["updated_at"]=(NOW-timedelta(seconds=8)).isoformat()
    assert not em.should_start_emergency_v1(p,now=NOW)
    assert not em.should_start_emergency_v1(None,now=NOW)


def test_account_latch_survives_duplicate_activation_and_is_scoped(tmp_path):
    db,b = prepare(tmp_path)
    assert em.emergency_active_v1("account-A",db_path=db)
    assert not em.emergency_active_v1("account-B",db_path=db)
    assert em.active_emergency_accounts_v1(db_path=db) == ("account-A",)
    em.activate_emergency_v1("account-A","ANOTHER",db_path=db,now=NOW+timedelta(seconds=5))
    assert em.load_emergency_v1("account-A",db_path=db).reason == "TEST"


def test_default_does_not_submit_live_orders(tmp_path,monkeypatch):
    monkeypatch.delenv("PRICEGAUGER_V3_EMERGENCY_AUTO_FLATTEN_ENABLED",raising=False)
    db,b=prepare(tmp_path)
    assert em.run_emergency_account_once_v1("account-A",b,db_path=db,now=NOW)=="PAUSED"
    assert b.sent==[]
    assert em.emergency_active_v1("account-A",db_path=db)


def test_confirmed_saxo_short_is_closed_and_flat_confirmed_twice(tmp_path,monkeypatch):
    monkeypatch.setenv("PRICEGAUGER_V3_EMERGENCY_AUTO_FLATTEN_ENABLED","true")
    db,b=prepare(tmp_path)
    assert em.run_emergency_account_once_v1("account-A",b,db_path=db,now=NOW)=="SUBMITTED"
    assert len(b.sent)==1
    assert em.run_emergency_account_once_v1("account-A",b,db_path=db,now=NOW+timedelta(seconds=1))=="RESOLVED"
    assert len(b.sent)==1
    assert em.run_emergency_account_once_v1("account-A",b,db_path=db,now=NOW+timedelta(seconds=2))=="VERIFYING"
    assert em.run_emergency_account_once_v1("account-A",b,db_path=db,now=NOW+timedelta(seconds=63))=="RESUMED"
    assert not em.emergency_active_v1("account-A",db_path=db)
    assert len(b.sent)==1


def test_uncertain_existing_order_does_not_duplicate(tmp_path,monkeypatch):
    monkeypatch.setenv("PRICEGAUGER_V3_EMERGENCY_AUTO_FLATTEN_ENABLED","true")
    db,b=prepare(tmp_path,state="UNKNOWN")
    assert em.run_emergency_account_once_v1("account-A",b,db_path=db,now=NOW)=="RESOLVING"
    assert len(b.sent)==0
    # The first missing-audit read is not permission to replay the old POST.
    assert em.run_emergency_account_once_v1("account-A",b,db_path=db,
        now=NOW+timedelta(seconds=5))=="RESOLVING"
    assert len(b.sent)==0


def test_stable_absent_broker_order_is_superseded_without_replaying_it(tmp_path,monkeypatch):
    monkeypatch.setenv("PRICEGAUGER_V3_EMERGENCY_AUTO_FLATTEN_ENABLED","true")
    db,b=prepare(tmp_path,state="UNKNOWN")
    assert em.run_emergency_account_once_v1("account-A",b,db_path=db,now=NOW)=="RESOLVING"
    assert em.run_emergency_account_once_v1("account-A",b,db_path=db,
        now=NOW+timedelta(seconds=16))=="RESOLVED"
    assert b.sent==[]
    # A new emergency close is based on fresh confirmed exposure only.
    assert em.run_emergency_account_once_v1("account-A",b,db_path=db,
        now=NOW+timedelta(seconds=20))=="SUBMITTED"
    assert len(b.sent)==1


def test_auth_failed_keeps_latch_and_does_not_submit(tmp_path,monkeypatch):
    monkeypatch.setenv("PRICEGAUGER_V3_EMERGENCY_AUTO_FLATTEN_ENABLED","true")
    db,b=prepare(tmp_path)
    from saxo_provider import SaxoError
    b.error=SaxoError("Authorization unavailable",status="REQUEST_FAILED",status_code=401)
    assert em.run_emergency_account_once_v1("account-A",b,db_path=db,now=NOW)=="BROKER_DOWN"
    assert em.load_emergency_v1("account-A",db_path=db).state=="AUTH_REQUIRED"
    assert not b.sent


def test_live_runtime_checks_account_emergency_at_post_boundary():
    src=Path("autotrader_v3_live_runtime_v1.py").read_text(encoding="utf-8")
    before=src.index("# Timestamp at the POST boundary")
    place=src.index("result=broker.place_order(order,confirm_live=True)",before)
    assert "if emergency_active_v1(e.account_id,db_path=db_path):" in src[before-550:before]
    assert before<place
    assert "SAXO_ORDER_POST_UNCERTAIN" in src[place:]
    worker=Path("worker.py").read_text(encoding="utf-8")
    assert "active_emergency_accounts_v1(db_path=str(db_path))" in worker
