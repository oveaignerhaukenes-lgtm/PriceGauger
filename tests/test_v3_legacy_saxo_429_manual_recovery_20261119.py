"""A historical Saxo rate-limit rejection may be reset manually, never blindly."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import autotrader_v3_instance_reset_v1 as reset
import autotrader_v3_operator_order_recovery_v1 as recovery
from autotrader_v3_order_guard_v1 import ensure_schema, pending_order, claim_reserved_for_submission_v3
from database import connect


DETAIL = ("SaxoError: REQUEST_FAILED · HTTP 429: "
          "{'ErrorCode': 'RateLimitExceeded', 'Message': 'Rate limit exceeded!'}")
NOW = datetime(2026, 11, 19, 19, 30, tzinfo=timezone.utc)
STAMP = "2026-11-19 17:28:29.250765+00:00"
INSTANCE = SimpleNamespace(
    instance_id="tech100-C", account_id="account-C", uic=4912, asset_type="CfdOnIndex"
)


class ReadOnlySaxo:
    def __init__(self, *, before=0.0, after=None, orders=()):
        self.calls = []
        self.before = before
        self.after = before if after is None else after
        self.orders = list(orders)
        self.client = self

    def _account_context_exact(self, account_id):
        assert account_id == "account-C"
        self.calls.append("account")
        return "key-C", "client-C"

    def signed_inventory_exact(self, **kwargs):
        assert kwargs == dict(account_id="account-C", uic=4912, asset_type="CfdOnIndex")
        self.calls.append("inventory")
        return self.before if self.calls.count("inventory") == 1 else self.after

    def _get(self, path, params=None):
        assert (path, params) == ("port/v1/orders/me", {"$top": 1000})
        self.calls.append("orders")
        return {"Data": list(self.orders)}

    def place_order(self, *args, **kwargs):
        raise AssertionError("A reset must not place or close Saxo orders")

    def _post(self, *args, **kwargs):
        raise AssertionError("A reset must never POST to Saxo")


def arrange(monkeypatch, tmp_path, *, detail=DETAIL, state="UNKNOWN", broker_order_id=None, updated=STAMP):
    db_path = str(tmp_path / "rate-limit-recovery.db")
    ensure_schema(db_path)
    with connect(db_path) as db:
        db.execute("""INSERT INTO autotrader_v3_order_guard
            (request_key,trader_id,account_id,uic,asset_type,state,broker_order_id,
             expected_inventory,submitted_amount,submitted_side,detail,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (
                "rejected-429", "tech100-C", "account-C", 4912, "CfdOnIndex", state,
                broker_order_id, 0.01, 0.01, "Buy", detail, updated,
            ))
    monkeypatch.setattr(recovery, "load_v3_instances_v1", lambda **kwargs: (INSTANCE,))
    monkeypatch.setattr(reset, "load_v3_instances_v1", lambda **kwargs: (INSTANCE,))
    return db_path


@pytest.mark.parametrize("detail", [
    "SaxoError: REQUEST_FAILED · HTTP 429: {'ErrorCode': 'OtherRateLimit'}",
    "SaxoError: REQUEST_FAILED · HTTP 408: {'ErrorCode': 'RateLimitExceeded'}",
    "SaxoError: CONNECTION_FAILED · HTTP 429: {'ErrorCode': 'RateLimitExceeded'}",
    "SaxoError: REQUEST_FAILED · HTTP 500: {'ErrorCode': 'RateLimitExceeded'}",
    "SaxoError: REQUEST_FAILED · HTTP 429: timeout",
])
def test_only_explicit_saxo_post_rate_limit_qualifies(detail):
    assert recovery.documented_saxo_rate_limit_v3({"state": "UNKNOWN", "detail": detail}) is False


def test_manual_reset_verifies_broker_twice_and_retains_audit_and_authority(monkeypatch, tmp_path):
    db_path = arrange(monkeypatch, tmp_path)
    broker = ReadOnlySaxo()
    result = reset.reset_instance_safely_v3(instance_id="tech100-C", db_path=db_path,
                                           broker=broker, now=NOW)
    assert result.status == "RATE_LIMIT_RECOVERED"
    assert "LIVE-tilstand" in result.detail
    assert broker.calls == ["account", "inventory", "orders", "inventory"]
    with connect(db_path) as db:
        row = db.execute("SELECT state,detail FROM autotrader_v3_order_guard WHERE request_key=?",
                         ("rejected-429",)).fetchone()
        assert row[0] == "REJECTED"
        assert DETAIL in row[1]
        assert "OPERATOR_RECOVERED_CONFIRMED_SAXO_RATE_LIMIT" in row[1]
    assert not claim_reserved_for_submission_v3(request_key="rejected-429", db_path=db_path)


@pytest.mark.parametrize("before,after,orders", [
    (0.01, 0.01, ()),
    (0.0, 0.01, ()),
    (0.0, 0.0, ({"AccountId": "account-C", "OrderId": "active"},)),
    (0.0, 0.0, ({"OrderId": "unattributed"},)),
    (float("nan"), float("nan"), ()),
])
def test_reset_denied_if_broker_evidence_is_not_exact(monkeypatch, tmp_path, before, after, orders):
    db_path = arrange(monkeypatch, tmp_path)
    with pytest.raises(recovery.OrderRecoveryDeniedV3):
        reset.reset_instance_safely_v3(instance_id="tech100-C", db_path=db_path,
                                       broker=ReadOnlySaxo(before=before, after=after, orders=orders),
                                       now=NOW)
    assert pending_order(account_id="account-C", uic=4912, asset_type="CfdOnIndex", db_path=db_path)["state"] == "UNKNOWN"


@pytest.mark.parametrize("overrides", [
    {"detail": "SaxoError: REQUEST_FAILED · HTTP 429: timeout"},
    {"broker_order_id": "12345678"},
    {"state": "SUBMITTED"},
    {"updated": "2026-11-19 19:29:59+00:00"},
])
def test_ambiguous_or_recent_unknown_remains_locked(monkeypatch, tmp_path, overrides):
    db_path = arrange(monkeypatch, tmp_path, **overrides)
    broker = ReadOnlySaxo()
    with pytest.raises(recovery.OrderRecoveryDeniedV3):
        reset.reset_instance_safely_v3(instance_id="tech100-C", db_path=db_path,
                                       broker=broker, now=NOW)
    assert pending_order(account_id="account-C", uic=4912, asset_type="CfdOnIndex", db_path=db_path)


def test_ui_describes_documented_rejection_but_never_trades():
    from pathlib import Path
    ui = Path("autotrader_v3_instance_controls_ui_v1.py").read_text()
    assert "Saxo avviste ordre: HTTP 429 RateLimitExceeded" in ui
    assert "Kontroller Saxo / frigi ordrelås" in ui
    assert "Reset lukker ALDRI en Saxo-posisjon" in ui
