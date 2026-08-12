from __future__ import annotations

from trading_desk_products import MARKET_SEARCH_TERMS


def test_market_aliases_remain_bounded_to_configured_underlyings() -> None:
    assert set(MARKET_SEARCH_TERMS) == {"Gold", "Silver", "Brent", "Natural Gas", "DXY"}
