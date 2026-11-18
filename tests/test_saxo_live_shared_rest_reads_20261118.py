"""Saxo LIVE reference sharing must not weaken account/execution safety."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from time import sleep

import pytest

import autotrader_open_sizing_v2 as sizing
import saxo_rest_telemetry_v1 as telemetry
from autotrader_v3_live_saxo_v1 import SaxoLivePilotClientV3
from saxo_provider import LIVE_BASE_URL, SIM_BASE_URL, SaxoClient, SaxoError, SaxoInstrument


DETAILS = {
    "AssetType": "CfdOnIndex",
    "IsTradable": True,
    "NonTradableReason": "None",
    "AmountDecimals": 2,
    "MinimumTradeSize": 0.01,
    "ContractSize": 1,
    "CurrencyCode": "USD",
    "SupportedOrderTypes": ["Market"],
}


class Response:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status
        self.ok = status < 400
        self.headers = {}

    def json(self):
        return self.payload


class Session:
    def __init__(self, statuses=()):
        self.headers = {}
        self.requests = []
        self.lock = Lock()
        self.statuses = list(statuses)

    def get(self, url, *, params=None, timeout=None):
        with self.lock:
            self.requests.append((url, dict(params or {})))
            status = self.statuses.pop(0) if self.statuses else 200
        sleep(0.01)  # Force overlapping workers to exercise single-flight.
        if url.endswith("port/v1/accounts/me"):
            return Response({"Data": [
                {"AccountId": "A", "AccountKey": "acc-A", "ClientKey": "client"},
                {"AccountId": "B", "AccountKey": "acc-B", "ClientKey": "client"},
            ]}, status)
        return Response(dict(DETAILS) if status == 200 else {"Message": "rate-limited"}, status)


def client(token, session, *, live=True):
    return SaxoClient(
        access_token=token,
        base_url=LIVE_BASE_URL if live else SIM_BASE_URL,
        session=session,
    )


def instrument():
    return SaxoInstrument(asset="Tech100", uic=4912, asset_type="CfdOnIndex")


def rules(broker, account="acc-A"):
    return sizing.load_entry_instrument_rules_v2(
        broker, account_key=account, instrument=instrument()
    )


def test_live_rules_single_flight_across_independent_sessions():
    session = Session()
    one = client("cache-singleflight-test", session)
    two = client("cache-singleflight-test", session)
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(rules, (one, two)))
    assert result[0] == result[1]
    assert len(session.requests) == 1


def test_rules_cache_isolated_by_account_token_and_environment():
    session = Session()
    a = client("cache-isolation-test-a", session)
    b = client("cache-isolation-test-b", session)
    rules(a, "account-A")
    rules(a, "account-B")
    rules(b, "account-A")
    rules(client("cache-isolation-test-a", session, live=False), "account-A")
    assert len(session.requests) == 4


def test_expired_rules_must_refetch_and_never_serve_stale_on_429(monkeypatch):
    clock = [50.0]
    monkeypatch.setattr(sizing.time, "monotonic", lambda: clock[0])
    session = Session(statuses=[200, 429, 200])
    broker = client("cache-expiry-test", session)
    rules(broker, "expiry-account")
    clock[0] += sizing._LIVE_RULES_TTL_SECONDS + 1
    with pytest.raises(SaxoError) as error:
        rules(broker, "expiry-account")
    assert error.value.status_code == 429
    rules(broker, "expiry-account")
    assert len(session.requests) == 3


def test_sim_and_test_double_are_uncached():
    session = Session()
    broker = client("sim-test", session, live=False)
    rules(broker, "acc-A")
    rules(broker, "acc-A")
    assert len(session.requests) == 2


def test_account_identity_reuses_snapshot_without_caching_fresh_accounts():
    session = Session()
    broker = SaxoLivePilotClientV3(client("accounts-test", session))
    assert len(broker.accounts()) == 2
    assert broker._account_context_exact("A") == ("acc-A", "client")
    assert broker._account_context_exact("B") == ("acc-B", "client")
    assert len(session.requests) == 1
    broker.accounts()  # loss/margin guards still force a fresh Saxo read
    assert len(session.requests) == 2


def test_account_identity_missing_or_duplicate_fails_closed():
    session = Session()
    broker = SaxoLivePilotClientV3(client("accounts-validation-test", session))
    with pytest.raises(Exception, match="identity is missing or ambiguous"):
        broker._account_context_exact("unknown")


def test_rest_telemetry_tracks_http_but_never_logs_account_key(caplog, monkeypatch):
    monkeypatch.setattr(telemetry, "_STARTED", 100.0)
    telemetry._COUNTS.clear()
    telemetry._RATE_LIMITED.clear()
    telemetry._RATE_REMAINING.clear()
    with caplog.at_level("INFO"):
        telemetry.record_saxo_http_v1(
            "GET", "ref/v1/instruments/details/4912/CfdOnIndex?AccountKey=secret",
            200, now=101.0
        )
        telemetry.record_saxo_http_v1(
            "GET", "port/v1/netpositions?AccountKey=secret", 429, now=161.0
        )
    assert "GET:ref/v1/instruments/details=1/min(429=0)" in caplog.text
    assert "GET:port/v1/netpositions=1/min(429=1)" in caplog.text
    assert telemetry.normalized_saxo_endpoint_v1("trade/v2/orders/precheck") == "trade/v2/orders/precheck"\n    assert telemetry.normalized_saxo_endpoint_v1("trade/v2/orders") == "trade/v2/orders"\n    assert "secret" not in caplog.text
