"""No duplicate account GET on a cost guard; still broker-authoritative costs."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from autotrader_v3_cost_guard_v1 import _exact_account, assess_transaction_cost_v3
from autotrader_v3_live_saxo_v1 import SaxoLivePilotClientV3
from saxo_provider import SaxoClient, LIVE_BASE_URL
import saxo_rest_telemetry_v1 as telemetry


class Response:
    ok=True
    status_code=200
    headers={}
    def __init__(self, data):
        self.data=data
    def json(self):
        return self.data


class Session:
    def __init__(self):
        self.headers={}
        self.paths=[]
    def get(self,url,params=None,timeout=None):
        path=url.split("/openapi/")[-1]
        self.paths.append((path,params))
        if path=="port/v1/accounts/me":
            return Response({"Data":[
                {"AccountId":"acct-A","AccountKey":"key-A","ClientKey":"client","Currency":"NOK"},
                {"AccountId":"acct-B","AccountKey":"key-B","ClientKey":"client","Currency":"NOK"},
            ]})
        if path=="trade/v1/infoprices":
            return Response({"Quote":{"Mid":24500.0}})
        if path=="cs/v1/tradingconditions/cost/key-A/4912/CfdOnIndex":
            return Response({"Cost":{"Long":{"TotalCostPct":0.1},
                                     "Short":{"TotalCostPct":0.2}}})
        raise AssertionError("unexpected GET: "+path)


def client():
    s=Session()
    return SaxoLivePilotClientV3(SaxoClient(
        access_token="test-token",base_url=LIVE_BASE_URL,session=s)),s


def test_v3_cost_guard_reuses_verified_identity_and_still_reads_fresh_cost():
    broker,session=client()
    broker.accounts()  # Existing cycle-wide Saxo account validation.
    result=assess_transaction_cost_v3(
        broker=broker,account_id="acct-A",market_name="Tech100",
        uic=4912,asset_type="CfdOnIndex",amount=0.01)
    assert not result.blocked
    assert result.max_total_cost_pct==pytest.approx(.2)
    assert [p for p,_ in session.paths].count("port/v1/accounts/me")==1
    assert [p for p,_ in session.paths].count("trade/v1/infoprices")==1
    assert [p for p,_ in session.paths].count(
        "cs/v1/tradingconditions/cost/key-A/4912/CfdOnIndex")==1


def test_unknown_v3_account_fails_closed_without_using_another_account_key():
    broker,session=client()
    broker.accounts()
    assessment=assess_transaction_cost_v3(
        broker=broker,account_id="acct-X",market_name="Tech100",
        uic=4912,asset_type="CfdOnIndex",amount=0.01)
    assert assessment.blocked
    assert "missing or ambiguous" in assessment.detail
    assert [p for p,_ in session.paths]==["port/v1/accounts/me"]


def test_v3_cost_guard_without_prior_listing_makes_exactly_one_account_get():
    broker,session=client()
    assert _exact_account(broker,"acct-A")[0]=="key-A"
    assert [p for p,_ in session.paths]==["port/v1/accounts/me"]


def test_generic_broker_cost_guard_still_reloads_accounts():
    broker=SimpleNamespace(accounts=lambda: [
        {"AccountId":"A","AccountKey":"key-A","Currency":"NOK"}])
    assert _exact_account(broker,"A")==("key-A","NOK")


def test_rest_latency_reports_endpoint_distributions_without_identity(caplog,monkeypatch):
    monkeypatch.setattr(telemetry,"_STARTED",100.0)
    for name in ("_COUNTS","_RATE_LIMITED","_RATE_REMAINING","_LATENCY_SECONDS"):
        getattr(telemetry,name).clear()
    with caplog.at_level("INFO"):
        for t in (0.02,0.1,0.5,1.2):
            telemetry.record_saxo_http_v1(
                "GET","ref/v1/instruments/details/4912/CfdOnIndex?AccountKey=secret",
                200,now=101.0,latency_seconds=t)
        telemetry.record_saxo_http_v1(
            "GET","port/v1/accounts/me?AccountKey=secret",429,
            now=161.0,latency_seconds=.3)
    assert "p50_ms=500" in caplog.text
    assert "p95_ms=1200" in caplog.text
    assert "p99_ms=1200" in caplog.text
    assert "429=1" in caplog.text
    assert "secret" not in caplog.text
    assert not telemetry._LATENCY_SECONDS
