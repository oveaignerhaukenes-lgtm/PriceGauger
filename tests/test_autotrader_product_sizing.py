from __future__ import annotations

import pytest

from autotrader_product_sizing import fx_product_per_input, quote_price, size_from_budget
from saxo_provider import SaxoInstrument
from trading_desk_products import LeveragedProductDetails


class _Client:
    def __init__(self, *, product_price=4.0, fx_pairs=None):
        self.product_price = product_price
        self.fx_pairs = fx_pairs or {}

    def info_price(self, instrument):
        if instrument.asset_type == "FxSpot":
            rate = self.fx_pairs[instrument.symbol]
            return {"Quote": {"Bid": rate - 0.001, "Ask": rate + 0.001, "Mid": rate}}
        return {"Quote": {"Bid": self.product_price - 0.1, "Ask": self.product_price, "Mid": self.product_price - 0.05}}

    def search_instruments(self, keywords, *, asset_types):
        assert asset_types == "FxSpot"
        normalized = "".join(character for character in keywords.upper() if character.isalpha())
        if normalized in self.fx_pairs:
            return [
                SaxoInstrument(
                    asset=normalized,
                    uic=900,
                    asset_type="FxSpot",
                    symbol=normalized,
                    description=normalized,
                )
            ]
        return []


def _details(*, currency="EUR", minimum=1.0, increment=1.0, decimals=0):
    return LeveragedProductDetails(
        instrument=SaxoInstrument(
            asset="Brent",
            uic=123,
            asset_type="MiniFuture",
            symbol="MINI BRENT L",
            description="Mini Brent Long",
        ),
        direction="Long",
        is_tradable=True,
        currency=currency,
        barrier=70.0,
        financing_level=72.0,
        strike=None,
        default_amount=1.0,
        minimum_trade_size=minimum,
        increment_size=increment,
        amount_decimals=decimals,
    )


def test_quote_price_uses_ask_for_buy_and_bid_for_sell():
    payload = {"Quote": {"Bid": 9.8, "Ask": 10.2, "Mid": 10.0}}
    assert quote_price(payload, action="Buy") == 10.2
    assert quote_price(payload, action="Sell") == 9.8


def test_budget_sizing_converts_nok_to_product_currency_and_rounds_down():
    client = _Client(product_price=4.0, fx_pairs={"NOKEUR": 0.085})
    result = size_from_budget(
        client,
        _details(currency="EUR"),
        budget=2000.0,
        input_currency="NOK",
        action="Buy",
    )

    assert result.market_direction == "Long"
    assert result.input_currency == "NOK"
    assert result.product_currency == "EUR"
    assert result.amount == 42.0
    assert result.estimated_value_product == pytest.approx(168.0)
    assert result.estimated_value_input == pytest.approx(168.0 / 0.084)
    assert result.estimated_value_input <= 2000.0


def test_budget_sizing_uses_reverse_fx_pair_when_direct_is_unavailable():
    client = _Client(product_price=10.0, fx_pairs={"EURNOK": 12.0})
    result = size_from_budget(
        client,
        _details(currency="EUR"),
        budget=1200.0,
        input_currency="NOK",
        action="Buy",
    )

    assert result.fx_product_per_input == pytest.approx(1.0 / 12.001)
    assert result.amount == 9.0


def test_budget_below_minimum_trade_size_fails_closed():
    client = _Client(product_price=100.0)
    with pytest.raises(ValueError, match="for lavt"):
        size_from_budget(
            client,
            _details(currency="NOK", minimum=5.0, increment=1.0),
            budget=200.0,
            input_currency="NOK",
            action="Buy",
        )


def test_unknown_product_currency_does_not_guess():
    client = _Client(product_price=10.0)
    with pytest.raises(ValueError, match="produktvaluta"):
        size_from_budget(
            client,
            _details(currency=None),
            budget=2000.0,
            input_currency="NOK",
        )
