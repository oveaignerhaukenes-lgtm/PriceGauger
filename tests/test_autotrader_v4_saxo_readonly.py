"""GET-only Saxo account validation without credentials/network calls."""

from decimal import Decimal
import pytest

from autotrader_v4 import SaxoBoundary
from autotrader_v4.saxo_readonly import SaxoReadOnlyGateway


def sample_response(path, params):
    if path == "port/v1/accounts/me":
        return {"Data": [
            {"AccountId": "A", "AccountKey": "KEY_A", "ClientKey": "CLIENT_A", "Currency": "NOK"},
            {"AccountId": "B", "AccountKey": "KEY_B", "ClientKey": "CLIENT_A", "Currency": "USD"},
        ]}
    if path == "port/v1/balances":
        assert params["AccountKey"] == "KEY_A"
        assert params["ClientKey"] == "CLIENT_A"
        return {"Currency": "NOK", "TotalValue": 1500.32, "CashBalance": 1000.0,
                "CalculationReliability": "Ok", "AccountId": "A"}
    if path == "port/v1/netpositions":
        assert params["AccountKey"] == "KEY_A"
        assert params["ClientKey"] == "CLIENT_A"
        assert params["Uic"] == 4912
        return {"Data": [{
            "NetPositionBase": {"Uic": 4912, "AssetType": "CfdOnIndex",
                                "AmountLong": 0.01, "AmountShort": 0.0}
        }]}
    raise AssertionError(f"Unexpected request: {path}")


def test_accounts_and_balance_are_scoped_get_only():
    calls = []
    def get(path, params):
        calls.append((path, dict(params)))
        return sample_response(path, params)
    broker = SaxoReadOnlyGateway(get)
    assert tuple(a.account_id for a in broker.accounts()) == ("A", "B")
    value = broker.balance(account_id="A")
    assert value.currency == "NOK"
    assert value.total_value == Decimal("1500.32")
    assert value.calculation_reliability == "Ok"
    assert all(path.startswith("port/v1/") for path, _ in calls)


def test_exact_inventory_is_scoped_and_mismatches_are_rejected():
    b = SaxoBoundary("A", 4912, "CfdOnIndex")
    gateway = SaxoReadOnlyGateway(sample_response)
    assert len(gateway.net_positions(boundary=b)) == 1
    def wrong_uic(path, params):
        value = sample_response(path, params)
        if path == "port/v1/netpositions":
            value["Data"][0]["NetPositionBase"]["Uic"] = 4913
        return value
    with pytest.raises(ValueError, match="product boundary"):
        SaxoReadOnlyGateway(wrong_uic).net_positions(boundary=b)
    def wrong_account(path, params):
        value = sample_response(path, params)
        if path == "port/v1/netpositions":
            value["Data"][0]["AccountId"] = "B"
        return value
    with pytest.raises(ValueError, match="account boundary"):
        SaxoReadOnlyGateway(wrong_account).net_positions(boundary=b)


def test_never_guess_missing_unverified_or_conflicting_broker_facts():
    def absent_history(path, params):
        if path == "port/v1/accounts/me":
            return {"Data": [{"AccountId":"A","AccountKey":"KA","ClientKey":"CA","Currency":"NOK"}]}
        return {"Currency": "NOK", "CashBalance": 500}
    with pytest.raises(ValueError, match="numeric"):
        SaxoReadOnlyGateway(absent_history).balance(account_id="A")
    def wrong_currency(path, params):
        if path == "port/v1/accounts/me":
            return sample_response(path, params)
        result = sample_response(path, params)
        result["Currency"] = "USD"
        return result
    with pytest.raises(ValueError, match="currency"):
        SaxoReadOnlyGateway(wrong_currency).balance(account_id="A")
    with pytest.raises(ValueError, match="unavailable"):
        SaxoReadOnlyGateway(sample_response).balance(account_id="UNKNOWN")


def test_pagination_is_not_silently_treated_as_complete():
    def next_page(path, params):
        value = sample_response(path, params)
        if path == "port/v1/netpositions":
            value["__next"] = "next-page"
        return value
    with pytest.raises(ValueError, match="incomplete"):
        SaxoReadOnlyGateway(next_page).net_positions(
            boundary=SaxoBoundary("A", 4912, "CfdOnIndex")
        )
