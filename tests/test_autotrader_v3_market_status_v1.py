from autotrader_v3_live_saxo_v1 import SaxoLivePilotClientV3
from saxo_provider import LIVE_BASE_URL


class _Client:
    base_url = LIVE_BASE_URL

    def _get(self, path, params=None):
        if path == "port/v1/accounts/me":
            return {"Data": [{"AccountId": "A1", "AccountKey": "K1", "ClientKey": "C1"}]}
        if path == "trade/v1/infoprices":
            assert params == {
                "AccountKey": "K1",
                "Uic": 4912,
                "AssetType": "CfdOnIndex",
                "FieldGroups": "InstrumentPriceDetails,Quote",
            }
            return {
                "InstrumentPriceDetails": {"IsMarketOpen": False},
                "Quote": {"MarketState": "Closed", "ErrorCode": "None"},
            }
        raise AssertionError(path)


def test_v3_live_adapter_reads_exact_saxo_market_state():
    broker = SaxoLivePilotClientV3(_Client())
    status = broker.market_status_exact(
        account_id="A1",
        uic=4912,
        asset_type="CfdOnIndex",
    )
    assert status.is_open is False
    assert status.market_state == "Closed"
    assert status.quote_error is None
