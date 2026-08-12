from __future__ import annotations

from trading_desk_products import MARKET_SEARCH_TERMS


def test_common_market_aliases_are_explicit() -> None:
    assert MARKET_SEARCH_TERMS["Silver"] == ("Silver", "XAG", "XAGUSD")
    assert "ICE Brent" in MARKET_SEARCH_TERMS["Brent"]
    assert "Henry Hub" in MARKET_SEARCH_TERMS["Natural Gas"]
