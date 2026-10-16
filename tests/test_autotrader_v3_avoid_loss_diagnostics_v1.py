"""Saxo diagnostic runs GET-only, never asserts permission to trade."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from autotrader_v3_avoid_loss_diagnostics_v1 import diagnose_saxo_avoid_loss_v1

T=datetime(2026,10,16,20,0,tzinfo=timezone.utc)


class ReadOnlyBroker:
    def __init__(self):
        self.calls=[]
        self.currency="NOK"
        self.nets=[]
        self.positions=[]
        self.broken=None

    def accounts(self):
        self.calls.append("accounts")
        return ({"AccountId":"SECRET_ACCOUNT","Currency":self.currency},)

    def net_positions_exact(self, **kw):
        self.calls.append("net_positions_exact")
        assert kw == {"account_id":"SECRET_ACCOUNT","uic":4912,
                      "asset_type":"CfdOnIndex"}
        if self.broken=="net":
            raise RuntimeError("secret token bank account SECRET_ACCOUNT")
        return tuple(self.nets)

    def positions_exact(self, **kw):
        self.calls.append("positions_exact")
        assert kw == {"account_id":"SECRET_ACCOUNT","uic":4912,
                      "asset_type":"CfdOnIndex"}
        if self.broken=="position":
            raise RuntimeError("secret token position id SECRET_POSITION")
        return tuple(self.positions)

    def place_order(self,*args,**kw):
        raise AssertionError("READ ONLY: order placement forbidden")

    def precheck(self,*args,**kw):
        raise AssertionError("READ ONLY: precheck forbidden")

    def _post(self,*args,**kw):
        raise AssertionError("READ ONLY: POST forbidden")


def request(b,at=T):
    return diagnose_saxo_avoid_loss_v1(
        broker=b,account_id="SECRET_ACCOUNT",uic=4912,
        asset_type="CfdOnIndex",now=at)


def set_open(b,*,direction="Buy"):
    qty=.01
    b.nets=[{"NetPositionBase":{
        "AccountId":"SECRET_ACCOUNT","Uic":4912,"AssetType":"CfdOnIndex",
        "AmountLong":qty if direction=="Buy" else 0.,
        "AmountShort":qty if direction=="Sell" else 0.,
    }}]
    b.positions=[{
        "PositionId":"SECRET_POSITION",
        "PositionBase":{
            "AccountId":"SECRET_ACCOUNT","Uic":4912,"AssetType":"CfdOnIndex",
            "Amount":qty,"Status":"Open","CanBeClosed":True,
        },
        "PositionView":{
            "ProfitLossOnTradeInBaseCurrency":23.1,
            "TradeCostsTotalInBaseCurrency":.44,
            "CalculationReliability":"Ok",
            "CurrentPriceDelayMinutes":0,
            "CurrentPriceLastTraded":T.isoformat(),
        },
    }]


def test_flat_is_observed_never_live_ready_and_uses_get_only():
    b=ReadOnlyBroker()
    r=request(b)
    assert r.status=="FLAT_OBSERVED" and not r.live_ready
    assert r.code=="NO_OPEN_POSITION_FOR_PNL_VALIDATION"
    assert b.calls==["accounts","net_positions_exact","positions_exact"]


@pytest.mark.parametrize("direction",["Buy","Sell"])
def test_open_long_short_shows_only_codes_and_no_live_permission(direction):
    b=ReadOnlyBroker()
    set_open(b,direction=direction)
    r=request(b)
    assert r.status=="FIELDS_OBSERVED_NOT_LIVE_READY"
    assert r.code=="FROZEN_ENTRY_MARGIN_FINANCING_AND_CLOSE_TO_FLAT_UNPROVEN"
    assert not r.live_ready
    assert "SIGNED_INVENTORY_MATCH" in r.observed
    assert "COST_BASE_FIELD_NUMERIC" in r.observed
    text=str(r.public_dict())
    for secret in ("SECRET_ACCOUNT","SECRET_POSITION","23.1",".01","0.44"):
        assert secret not in text


@pytest.mark.parametrize("mutation,reason,phase",[
    (lambda b: b.positions[0]["PositionView"].update(
        CurrentPriceLastTraded=4250.1),"LAST_TRADED_MARKER_NOT_TIMESTAMP","QUOTE"),
    (lambda b: b.positions[0]["PositionView"].pop(
        "CurrentPriceLastTraded"),"LAST_TRADED_TIMESTAMP_MISSING","QUOTE"),
    (lambda b: b.positions[0]["PositionView"].update(
        CurrentPriceLastTraded=(T-timedelta(seconds=15)).isoformat()
    ),"LAST_TRADED_TIMESTAMP_STALE","QUOTE"),
    (lambda b: b.positions[0]["PositionView"].update(
        CalculationReliability="Pending"),"QUOTE_RELIABILITY_UNVERIFIED","QUOTE"),
    (lambda b: b.positions[0]["PositionView"].update(
        CurrentPriceDelayMinutes=15),"QUOTE_DELAYED","QUOTE"),
    (lambda b: b.positions[0]["PositionView"].pop(
        "TradeCostsTotalInBaseCurrency"),"TRADE_COST_BASE_CURRENCY_INVALID","COSTS"),
    (lambda b: b.positions[0]["PositionView"].update(
        ProfitLossOnTradeInBaseCurrency=float("nan")),"TRADE_PNL_BASE_CURRENCY_INVALID","PNL"),
    (lambda b: b.nets[0]["NetPositionBase"].update(
        AmountLong=None,AmountShort=None,Amount=.01
    ),"NET_DIRECTION_OR_AMOUNT_INVALID","NET_DIRECTION"),
    (lambda b: b.positions[0]["PositionBase"].update(
        Amount=.02),"POSITION_QUANTITY_NOT_MATCHING","INVENTORY_MATCH"),
    (lambda b: b.positions[0].pop("PositionView"),"POSITION_VIEW_MISSING","POSITION_SHAPE"),
    (lambda b: b.positions[0]["PositionBase"].update(
        AccountId="WRONG"),"POSITION_ACCOUNT_MISMATCH","POSITION_IDENTITY"),
])
def test_failure_phase_is_precise_and_redacted(mutation,reason,phase):
    b=ReadOnlyBroker()
    set_open(b)
    mutation(b)
    r=request(b)
    assert r.status=="BLOCKED" and r.phase==phase and r.code==reason
    assert not r.live_ready
    assert "SECRET" not in str(r.public_dict())


@pytest.mark.parametrize("broken,phase,reason",[
    ("net","NET_GET","SAXO_NET_GET_FAILED"),
    ("position","POSITION_GET","SAXO_POSITION_GET_FAILED"),
])
def test_broker_errors_do_not_leak_raw_saxo_content(broken,phase,reason):
    b=ReadOnlyBroker()
    set_open(b)
    b.broken=broken
    r=request(b)
    assert (r.status,r.phase,r.code)==("BLOCKED",phase,reason)
    assert "token" not in str(r.public_dict())
    assert "SECRET" not in str(r.public_dict())


def test_multiple_positions_fail_closed_and_do_not_inspect_pnl():
    b=ReadOnlyBroker()
    set_open(b)
    b.positions.append(dict(b.positions[0],PositionId="SECRET_TWO"))
    r=request(b)
    assert r.phase=="POSITION_COUNT"
    assert r.code=="MULTIPLE_POSITIONS_NOT_SUPPORTED"


def test_foreign_currency_not_allowed_to_probe_product():
    b=ReadOnlyBroker()
    b.currency="USD"
    r=request(b)
    assert r.code=="ACCOUNT_NOT_VERIFIED_NOK"
    assert b.calls==["accounts"]


def test_readonly_ui_is_on_demand_inside_shared_instance_controls():
    controls=Path("autotrader_v3_instance_controls_ui_v1.py").read_text()
    fleet=Path("autotrader_v3_fleet_ui_v1.py").read_text()
    assert "diagnose_saxo_avoid_loss_v1(" in controls
    assert "key=f'{key_prefix}:avoid-loss-readonly:{trader_id}'" in controls
    assert "if st.button(" in controls
    assert "render_v3_instance_controls_v1(item" in fleet
    assert "LIVE-gate: LUKKET" in controls
