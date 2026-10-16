"""GET-only Saxo contract tests; no account mutation and no fake LIVE readiness."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from autotrader_v3_avoid_loss_readiness_v1 import inspect_saxo_avoid_loss_readonly_v1
from autotrader_v3_live_saxo_v1 import SaxoLivePilotClientV3
from saxo_provider import LIVE_BASE_URL
from saxo_trading import SaxoTradingSafetyError


T=datetime(2026,10,16,14,0,tzinfo=timezone.utc)


class FakeBroker:
    def __init__(self):
        self.currency="NOK"
        self.positions=[]
        self.net=[]
        self.calls=[]
    def accounts(self):
        self.calls.append("accounts")
        return ({"AccountId":"exact","Currency":self.currency},)
    def net_positions_exact(self, **kw):
        self.calls.append("net_positions_exact")
        assert kw == {"account_id":"exact","uic":4912,"asset_type":"CfdOnIndex"}
        return tuple(self.net)
    def positions_exact(self, **kw):
        self.calls.append("positions_exact")
        assert kw == {"account_id":"exact","uic":4912,"asset_type":"CfdOnIndex"}
        return tuple(self.positions)
    def place_order(self, *a, **kw):
        raise AssertionError("GET-only probe must never place order")
    def precheck(self, *a, **kw):
        raise AssertionError("GET-only probe must never precheck/POST")


def request(broker, at=T):
    return inspect_saxo_avoid_loss_readonly_v1(
        broker=broker,account_id="exact",uic=4912,asset_type="CfdOnIndex",
        now=at)


def make_open(broker, *, direction="Buy", price_at=T):
    size=0.01
    broker.net=[{
        "NetPositionBase":{
            "AccountId":"exact","Uic":4912,"AssetType":"CfdOnIndex",
            "AmountLong":size if direction=="Buy" else 0.,
            "AmountShort":size if direction=="Sell" else 0.,
        }}]
    broker.positions=[{
        "PositionId":"P1",
        "PositionBase":{"AccountId":"exact","Uic":4912,"AssetType":"CfdOnIndex",
                        "Amount":size,"Status":"Open","CanBeClosed":True},
        "PositionView":{
            "CalculationReliability":"Ok","CurrentPriceDelayMinutes":0,
            "CurrentPriceLastTraded":price_at.isoformat(),
            "ProfitLossOnTradeInBaseCurrency":10.0,
            "TradeCostsTotalInBaseCurrency":0.5,
        }}]


def test_flat_nok_account_is_visible_but_not_authorized_to_trade():
    b=FakeBroker()
    report=request(b)
    assert report.status=="FLAT_OBSERVED"
    assert not report.live_ready
    assert "NO_CONFIRMED_ENTRY_MARGIN" in report.blockers
    assert b.calls==["accounts","net_positions_exact","positions_exact"]
    assert "exact" not in str(report.public_dict())


@pytest.mark.parametrize("direction",["Buy","Sell"])
def test_exact_open_position_fields_are_observed_but_live_gate_stays_closed(direction):
    b=FakeBroker()
    make_open(b,direction=direction)
    report=request(b)
    assert report.status=="POSITION_FIELDS_OBSERVED"
    assert not report.live_ready
    assert "NO_CONFIRMED_CLOSE_TO_FLAT" in report.blockers
    assert "POSITION_PNL_AND_COST_FIELDS_PRESENT" in report.observed
    assert "P1" not in str(report.public_dict())
    assert "10.0" not in str(report.public_dict())


def test_usd_account_rejected_without_reading_positions():
    b=FakeBroker()
    b.currency="USD"
    report=request(b)
    assert report.status=="BLOCKED"
    assert report.blockers==("ACCOUNT_CURRENCY_NOT_NOK",)
    assert b.calls==["accounts"]


@pytest.mark.parametrize("mode,reason",[
    ("missing_timestamp","FRESH_RELIABLE_QUOTE_UNVERIFIED"),
    ("stale","FRESH_RELIABLE_QUOTE_UNVERIFIED"),
    ("future","FRESH_RELIABLE_QUOTE_UNVERIFIED"),
    ("delayed","FRESH_RELIABLE_QUOTE_UNVERIFIED"),
    ("unreliable","FRESH_RELIABLE_QUOTE_UNVERIFIED"),
    ("bad_account","RETURNED_ACCOUNT_MISMATCH"),
    ("bad_size","SIGNED_INVENTORY_NOT_ONE_POSITION"),
    ("cannot_close","POSITION_CANNOT_CLOSE"),
])
def test_invalid_or_unreliable_position_fails_closed(mode,reason):
    b=FakeBroker()
    make_open(b)
    v=b.positions[0]["PositionView"]
    p=b.positions[0]["PositionBase"]
    if mode=="missing_timestamp":v.pop("CurrentPriceLastTraded")
    if mode=="stale":v["CurrentPriceLastTraded"]=(T-timedelta(seconds=11)).isoformat()
    if mode=="future":v["CurrentPriceLastTraded"]=(T+timedelta(seconds=1)).isoformat()
    if mode=="delayed":v["CurrentPriceDelayMinutes"]=15
    if mode=="unreliable":v["CalculationReliability"]="PricePending"
    if mode=="bad_account":p["AccountId"]="another"
    if mode=="bad_size":p["Amount"]=0.02
    if mode=="cannot_close":p["CanBeClosed"]=False
    report=request(b)
    assert report.status=="BLOCKED"
    assert report.blockers==(reason,)
    assert not report.live_ready


def test_ambiguous_multiple_positions_never_claim_safe():
    b=FakeBroker()
    make_open(b)
    b.positions.append(dict(b.positions[0],PositionId="P2"))
    report=request(b)
    assert report.status=="BLOCKED"
    assert report.blockers==("AMBIGUOUS_POSITION_COUNT",)


def test_broker_exception_never_leaks_message_or_identity():
    class Broken(FakeBroker):
        def net_positions_exact(self, **kw):
            raise RuntimeError("Bearer SECRET account exact P/L=100")
    report=request(Broken())
    assert report.blockers==("SAXO_READ_FAILED",)
    assert "SECRET" not in str(report.public_dict())
    assert "exact" not in str(report.public_dict())


def test_saxo_positions_read_is_account_scoped_and_never_posts():
    calls=[]
    class Client:
        base_url=LIVE_BASE_URL
        def _get(self,path,params=None):
            calls.append((path,params))
            if path=="port/v1/accounts/me":
                return {"Data":[{"AccountId":"exact","AccountKey":"KEY","ClientKey":"CLIENT"}]}
            assert path=="port/v1/positions"
            return {"Data":[{
                "PositionId":"P1",
                "PositionBase":{"AccountId":"exact","Uic":4912,
                                "AssetType":"CfdOnIndex","Amount":0.01},
                "PositionView":{"CalculationReliability":"Ok"},
            }]}
        def _post(self,*a,**k):
            raise AssertionError("unexpected POST")
    broker=SaxoLivePilotClientV3(Client())
    rows=broker.positions_exact(account_id="exact",uic=4912,asset_type="CfdOnIndex")
    assert rows[0]["PositionId"]=="P1"
    assert calls[-1][0]=="port/v1/positions"
    assert calls[-1][1]["AccountKey"]=="KEY"
    assert calls[-1][1]["ClientKey"]=="CLIENT"
    assert calls[-1][1]["FieldGroups"]=="PositionBase,PositionView"


def test_individual_saxo_position_reader_rejects_ambiguous_or_foreign_rows():
    for mode in ("different_account","next_page","two"):
        class Client:
            base_url=LIVE_BASE_URL
            def _get(self,path,params=None):
                if path=="port/v1/accounts/me":
                    return {"Data":[{"AccountId":"exact","AccountKey":"KEY"}]}
                row={"PositionId":"P1","PositionBase":{
                    "AccountId":"another" if mode=="different_account" else "exact",
                    "Uic":4912,"AssetType":"CfdOnIndex","Amount":0.01}}
                payload={"Data":[row]}
                if mode=="next_page":payload["__next"]="skip=1000"
                if mode=="two":payload["Data"].append(dict(row,PositionId="P2"))
                return payload
        with pytest.raises(SaxoTradingSafetyError):
            SaxoLivePilotClientV3(Client()).positions_exact(
                account_id="exact",uic=4912,asset_type="CfdOnIndex")


def test_order_activity_returns_position_and_fill_details_for_future_audit():
    class Client:
        base_url=LIVE_BASE_URL
        def _get(self,path,params=None):
            if path=="port/v1/accounts/me":
                return {"Data":[{"AccountId":"exact","AccountKey":"KEY"}]}
            assert path=="cs/v1/audit/orderactivities"
            assert params["AccountKey"]=="KEY"
            return {"Data":[{
                "OrderId":"O1","AccountId":"exact",
                "Uic":4912,"AssetType":"CfdOnIndex",
                "Status":"FinalFill","SubStatus":"Confirmed",
                "PositionId":"P1","FilledAmount":0.01,"BuySell":"Buy",
            }]}
    r=SaxoLivePilotClientV3(Client()).order_activity_exact(
        account_id="exact",order_id="O1",uic=4912,asset_type="CfdOnIndex")
    assert r["status"]=="FinalFill" and r["sub_status"]=="Confirmed"
    assert r["position_id"]=="P1" and r["filled_amount"]==0.01
