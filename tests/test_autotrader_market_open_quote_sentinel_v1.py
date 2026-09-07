from __future__ import annotations

import pytest

import autotrader_live_open_v2 as live_open


class _Client:
    def __init__(self, *, is_open=True, error_code="None"):
        self.is_open = is_open
        self.error_code = error_code

    def _get(self, path, params=None):
        if path == "port/v1/accounts/me":
            return {"Data": [{"AccountId": "A1", "AccountKey": "K1"}]}
        if path == "trade/v1/infoprices":
            assert params["AccountKey"] == "K1"
            return {
                "InstrumentPriceDetails": {"IsMarketOpen": self.is_open},
                "Quote": {"ErrorCode": self.error_code, "Bid": 100.0, "Ask": 100.1},
            }
        raise AssertionError(path)


def test_string_none_quote_error_is_treated_as_no_error() -> None:
    live_open._require_market_open_for_open_v1(
        _Client(error_code="None"), account_id="A1", uic=4912, asset_type="CfdOnIndex"
    )


def test_real_quote_error_still_blocks_open() -> None:
    with pytest.raises(ValueError, match="SAXO_MARKET_QUOTE_ERROR:PriceTemporarilyUnavailable"):
        live_open._require_market_open_for_open_v1(
            _Client(error_code="PriceTemporarilyUnavailable"),
            account_id="A1",
            uic=4912,
            asset_type="CfdOnIndex",
        )


def test_market_must_still_be_explicitly_open() -> None:
    with pytest.raises(ValueError, match="SAXO_MARKET_NOT_EXPLICITLY_OPEN"):
        live_open._require_market_open_for_open_v1(
            _Client(is_open=False, error_code="None"),
            account_id="A1",
            uic=4912,
            asset_type="CfdOnIndex",
        )
