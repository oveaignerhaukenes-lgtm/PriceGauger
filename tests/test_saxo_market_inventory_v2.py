from saxo_market_inventory_v2 import (
    asset_type_rows_for_ui_v2,
    market_inventory_rows_for_ui_v2,
    scan_saxo_market_inventory_v2,
)


class FakeSaxoClient:
    def __init__(self):
        self.instrument_params = []

    def _get(self, path, *, params=None):
        if path == "port/v1/accounts/me":
            return {
                "Data": [
                    {
                        "AccountKey": "acc-key",
                        "AccountId": "ABC12345",
                        "Currency": "NOK",
                        "Active": True,
                    }
                ]
            }
        if path == "ref/v1/instruments":
            self.instrument_params.append(dict(params or {}))
            keyword = (params or {}).get("Keywords")
            if keyword in {"Gold", "XAU"}:
                return {
                    "Data": [
                        {
                            "Identifier": 101,
                            "AssetType": "CfdOnFutures",
                            "SummaryType": "Instrument",
                            "Description": "Gold CFD",
                            "Symbol": "GOLD",
                            "ExchangeId": "",
                            "CurrencyCode": "USD",
                            "TradableAs": ["CfdOnFutures"],
                            "UnderlyingAssetType": "ContractFutures",
                        },
                        {
                            "Identifier": 202,
                            "AssetType": "Etc",
                            "SummaryType": "Instrument",
                            "Description": "Physical Gold ETC",
                            "Symbol": "PHAU",
                            "ExchangeId": "XLON",
                            "CurrencyCode": "USD",
                            "TradableAs": ["Etc"],
                        },
                    ]
                }
            return {"Data": []}
        raise AssertionError(path)


def test_inventory_search_does_not_pre_filter_asset_types():
    client = FakeSaxoClient()
    result = scan_saxo_market_inventory_v2(client, market="Gold")

    assert len(result.rows) == 2
    assert result.asset_type_count == 2
    assert all("AssetTypes" not in params for params in client.instrument_params)
    assert all(params["AccountKey"] == "acc-key" for params in client.instrument_params)
    assert all(params["IncludeNonTradable"] is True for params in client.instrument_params)


def test_inventory_deduplicates_alias_hits_and_keeps_query_provenance():
    result = scan_saxo_market_inventory_v2(FakeSaxoClient(), market="Gold")
    cfd = next(row for row in result.rows if row.asset_type == "CfdOnFutures")
    assert cfd.matched_queries == ("Gold", "XAU")
    assert cfd.underlying_asset_type == "ContractFutures"


def test_inventory_ui_exposes_asset_type_distribution_before_candidate_filtering():
    result = scan_saxo_market_inventory_v2(FakeSaxoClient(), market="Gold")
    counts = asset_type_rows_for_ui_v2(result)
    rows = market_inventory_rows_for_ui_v2(result.rows)

    assert {item["AssetType"] for item in counts} == {"CfdOnFutures", "Etc"}
    assert {item["AssetType"] for item in rows} == {"CfdOnFutures", "Etc"}
    assert any(item["Treff via"] == "Gold, XAU" for item in rows)
