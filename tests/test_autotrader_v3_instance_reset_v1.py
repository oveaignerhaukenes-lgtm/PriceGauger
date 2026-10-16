"""Operator reset per V3 account is fail-closed and does not change LIVE state."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import autotrader_v3_instance_reset_v1 as mod
from autotrader_v3_operator_order_recovery_v1 import OrderRecoveryDeniedV3

INST = SimpleNamespace(
    instance_id="tech100-a",account_id="account-A",
    uic=4912,asset_type="CfdOnIndex",
)


class ReadOnlyBroker:
    def __init__(self, *, before=0.02, after=None, orders=()):
        self.before=before
        self.after=before if after is None else after
        self.orders=list(orders)
        self.calls=[]
        self.client=self

    def _account_context_exact(self, account_id):
        assert account_id == "account-A"
        self.calls.append("account")
        return "account-key-A","client-A"

    def signed_inventory_exact(self, **kwargs):
        assert kwargs == dict(account_id="account-A",uic=4912,asset_type="CfdOnIndex")
        self.calls.append("inventory")
        return self.before if self.calls.count("inventory")==1 else self.after

    def _get(self,path,params=None):
        self.calls.append("orders")
        assert path == "port/v1/orders/me"
        assert params == {"$top":1000}
        return {"Data":self.orders}

    def place_order(self, *args, **kwargs):
        raise AssertionError("Operator reset cannot submit broker orders")

    def _post(self, *args, **kwargs):
        raise AssertionError("Operator reset cannot POST to broker")


def _arrange(monkeypatch, pendings=(None, None)):
    monkeypatch.setattr(mod, "load_v3_instances_v1", lambda **kw:(INST,))
    calls=iter(pendings)
    monkeypatch.setattr(mod, "pending_order_v3", lambda **kw:next(calls))


def test_clean_instance_rechecks_exact_saxo_without_changing_live_configuration(monkeypatch):
    _arrange(monkeypatch)
    b=ReadOnlyBroker()
    result=mod.reset_instance_safely_v3(instance_id=INST.instance_id,broker=b)
    assert result.status=="ALREADY_CLEAR"
    assert "LIVE-tilstand" in result.detail
    assert b.calls==["account","inventory","orders","inventory"]


@pytest.mark.parametrize("state",["SUBMITTING","SUBMITTED","UNKNOWN"])
def test_unverified_order_is_never_cleared(monkeypatch,state):
    _arrange(monkeypatch,({"request_key":"R1","state":state},))
    b=ReadOnlyBroker()
    with pytest.raises(OrderRecoveryDeniedV3,match="Uavklart Saxo-ordre"):
        mod.reset_instance_safely_v3(instance_id=INST.instance_id,broker=b)
    assert not b.calls


@pytest.mark.parametrize("orders,before,after",[
    ([{"AccountId":"account-A","OrderId":"working"}],0.02,0.02),
    ([{"OrderId":"account-not-confirmed"}],0.02,0.02),
    ([],0.02,0.03),
    ([],float("nan"),float("nan")),
])
def test_clean_instance_is_not_claimed_during_working_order_or_inventory_change(
    monkeypatch,orders,before,after
):
    _arrange(monkeypatch)
    with pytest.raises(OrderRecoveryDeniedV3):
        mod.reset_instance_safely_v3(
            instance_id=INST.instance_id,
            broker=ReadOnlyBroker(orders=orders,before=before,after=after))


def test_new_reservation_during_check_blocks_ready_claim(monkeypatch):
    _arrange(monkeypatch,(None,{"request_key":"R2","state":"RESERVED"}))
    with pytest.raises(OrderRecoveryDeniedV3,match="Ny ordre"):
        mod.reset_instance_safely_v3(
            instance_id=INST.instance_id,broker=ReadOnlyBroker())


def test_stale_reserved_delegates_to_atomic_broker_verified_path(monkeypatch):
    _arrange(monkeypatch,({"state":"RESERVED","request_key":"R1","broker_order_id":None},))
    seen=[]
    def safe(**kw):
        seen.append(kw)
        return "RESERVED frigjort. Ingen ordre sendt."
    monkeypatch.setattr(mod,"recover_stale_reserved_v3",safe)
    result=mod.reset_instance_safely_v3(
        instance_id=INST.instance_id,broker=ReadOnlyBroker())
    assert result.status=="RESERVATION_RECOVERED"
    assert seen[0]["request_key"]=="R1"
    assert seen[0]["instance_id"]=="tech100-a"
    assert "Neste ordinære signal" in result.detail


def test_reserved_with_broker_id_or_wrong_instance_is_denied(monkeypatch):
    _arrange(monkeypatch,({"state":"RESERVED","request_key":"R1","broker_order_id":"broker123"},))
    with pytest.raises(OrderRecoveryDeniedV3):
        mod.reset_instance_safely_v3(instance_id=INST.instance_id,broker=ReadOnlyBroker())
    with pytest.raises(OrderRecoveryDeniedV3):
        mod.reset_instance_safely_v3(instance_id="unknown",broker=ReadOnlyBroker())


def test_fleet_and_tradingdesk_share_canonical_per_instance_reset():
    controls=Path("autotrader_v3_instance_controls_ui_v1.py").read_text(encoding="utf8")
    fleet=Path("autotrader_v3_fleet_ui_v1.py").read_text(encoding="utf8")
    page=Path("pages/0_AutoTrader_V3.py").read_text(encoding="utf8")
    assert "reset_instance_safely_v3(instance_id=trader_id)" in controls
    assert ":safe-reset:{trader_id}" in controls
    assert "render_v3_instance_controls_v1(item" in fleet
    assert 'mark_order_v3(' not in page
    assert 'state="REJECTED"' not in page
    assert "Kontrollert reset/avstemming" in page
