from __future__ import annotations

from types import SimpleNamespace

import pytest

from market_watchlist_v2 import _series_for_market


class _Store:
    def __init__(self, closes):
        self._closes = tuple(closes)

    def load_range(self, **_kwargs):
        return [SimpleNamespace(close=value) for value in self._closes]


def test_watchlist_series_uses_recent_close_and_relative_change():
    row = _series_for_market(_Store([100.0, 101.0, 103.0]), "Gold")
    assert row["market"] == "Gold"
    assert row["price"] == 103.0
    assert row["change_pct"] == pytest.approx(3.0)
    assert row["points"] == [100.0, 101.0, 103.0]


def test_watchlist_series_fails_closed_without_bars():
    row = _series_for_market(_Store([]), "Silver")
    assert row == {"market": "Silver", "price": None, "change_pct": None, "points": []}


def test_watchlist_source_contains_progressive_disclosure_contract():
    source = __import__("inspect").getsource(__import__("market_watchlist_v2"))
    assert "pricegauger:watchlist-drawer:v2" in source
    assert "width >= 245" in source
    assert "cursor:'ew-resize'" in source
    assert "Kun presentasjon" in source
