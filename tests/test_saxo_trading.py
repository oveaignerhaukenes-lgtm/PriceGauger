from __future__ import annotations

import pytest

from saxo_provider import LIVE_BASE_URL, SIM_BASE_URL, SaxoClient, SaxoInstrument
from saxo_trading import SaxoOrderRequest, SaxoTradingClient, SaxoTradingSafetyError


class FakeResponse:
    def __init__(self, payload, *, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.ok = 200 <= status_code < 300

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, *, get_payload=None, post_payload=None):
        self.headers = {}
        self.get_payload = get_payload or {}
        self.post_payload = post_payload or {}
        self.posts = []

    def get(self, url, params=None, timeout=None):
        return FakeResponse(self.get_payload)

    def post(self, url, json=None, timeout=None):
        self.posts.append((url, json, timeout))
        return FakeResponse(self.post_payload)


def _instrument():
    return SaxoInstrument(
        asset="Gold",
        uic=123,
        asset_type="ContractFutures",
        symbol="TEST",
    )


def test_order_payload_is_manual_market_day_order():
    payload = SaxoOrderRequest(
        account_key="account-key",
        instrument=_instrument(),
        amount=1,
        buy_sell="buy",
    ).payload()

    assert payload == {
        "AccountKey": "account-key",
        "Amount": 1.0,
        "AssetType": "ContractFutures",
        "BuySell": "Buy",
        "ManualOrder": True,
        "OrderDuration": {"DurationType": "DayOrder"},
        "OrderType": "Market",
        "Uic": 123,
    }


def test_live_endpoint_is_rejected():
    client = SaxoClient("token", base_url=LIVE_BASE_URL, session=FakeSession())
    with pytest.raises(SaxoTradingSafetyError, match="SIM"):
        SaxoTradingClient(client)


def test_place_order_requires_explicit_sim_confirmation():
    client = SaxoClient("token", base_url=SIM_BASE_URL, session=FakeSession())
    trading = SaxoTradingClient(client)
    order = SaxoOrderRequest("account-key", _instrument(), 1, "Buy")

    with pytest.raises(SaxoTradingSafetyError, match="confirm_sim"):
        trading.place_order(order)


def test_accounts_are_read_from_saxo_me_endpoint():
    session = FakeSession(
        get_payload={
            "Data": [
                {
                    "AccountKey": "key-1",
                    "AccountId": "SIM-1",
                    "Currency": "NOK",
                    "Active": True,
                }
            ]
        }
    )
    client = SaxoClient("token", base_url=SIM_BASE_URL, session=session)
    accounts = SaxoTradingClient(client).accounts()

    assert len(accounts) == 1
    assert accounts[0].account_key == "key-1"
    assert accounts[0].account_id == "SIM-1"
    assert accounts[0].currency == "NOK"
    assert accounts[0].active is True


def test_precheck_and_confirmed_order_use_expected_endpoints():
    session = FakeSession(post_payload={"PreCheckResult": "Ok", "OrderId": "42"})
    client = SaxoClient("token", base_url=SIM_BASE_URL, session=session)
    trading = SaxoTradingClient(client)
    order = SaxoOrderRequest("account-key", _instrument(), 1, "Sell")

    assert trading.precheck(order)["PreCheckResult"] == "Ok"
    assert trading.place_order(order, confirm_sim=True)["OrderId"] == "42"

    assert session.posts[0][0].endswith("/trade/v2/orders/precheck")
    assert session.posts[1][0].endswith("/trade/v2/orders")
    assert session.posts[0][1]["ManualOrder"] is True
    assert session.posts[1][1]["BuySell"] == "Sell"
