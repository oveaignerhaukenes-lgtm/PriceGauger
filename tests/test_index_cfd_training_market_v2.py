from saxo_low_friction_candidates_v2 import scan_low_friction_margin_candidates_v2
from saxo_market_inventory_v2 import (
    INDEX_CFD_TRAINING_TERMS,
    MARKET_INVENTORY_PRECISE_TERMS,
    precise_market_rows_v2,
    scan_saxo_market_inventory_v2,
)


class FakeIndexClient:
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
            if keyword in {"USNAS100.I", "US500.I"}:
                return {
                    "Data": [
                        {
                            "Identifier": 9001 if keyword == "USNAS100.I" else 9002,
                            "AssetType": "CfdOnIndex",
                            "SummaryType": "Instrument",
                            "Description": "US Tech 100 NAS" if keyword == "USNAS100.I" else "US 500",
                            "Symbol": keyword,
                            "CurrencyCode": "USD",
                            "TradableAs": ["CfdOnIndex"],
                        }
                    ]
                }
            return {"Data": []}
        if path.startswith("cs/v1/tradingconditions/cost/"):
            return {
                "AccountCurrency": "NOK",
                "Cost": {
                    "Long": {"Currency": "NOK", "TotalCostPct": 0.01, "TradingCost": {}},
                    "Short": {"Currency": "NOK", "TotalCostPct": 0.01, "TradingCost": {}},
                },
            }
        raise AssertionError(path)

    def info_price(self, instrument):
        return {"Quote": {"Bid": 20000.0, "Ask": 20001.0}}

    def instrument_details(self, instrument):
        return {
            "MinimumTradeSize": 0.01,
            "IncrementSize": 0.01,
        }


def test_training_universe_uses_documented_exact_index_symbols_as_precise_terms():
    assert "USNAS100.I" in INDEX_CFD_TRAINING_TERMS
    assert "US500.I" in INDEX_CFD_TRAINING_TERMS
    assert MARKET_INVENTORY_PRECISE_TERMS["Index CFDs · training"] == INDEX_CFD_TRAINING_TERMS


def test_training_inventory_is_account_aware_and_product_agnostic():
    client = FakeIndexClient()
    result = scan_saxo_market_inventory_v2(client, market="Index CFDs · training", max_per_query=25)

    assert {row.asset_type for row in result.rows} == {"CfdOnIndex"}
    assert {row.symbol for row in precise_market_rows_v2(result)} == {"USNAS100.I", "US500.I"}
    assert all("AssetTypes" not in params for params in client.instrument_params)
    assert all(params["AccountKey"] == "acc-key" for params in client.instrument_params)


def test_index_tracker_cfds_flow_into_low_friction_candidate_scanner():
    client = FakeIndexClient()
    inventory = scan_saxo_market_inventory_v2(client, market="Index CFDs · training", max_per_query=25)
    result = scan_low_friction_margin_candidates_v2(client, inventory=inventory, max_products=20)

    assert len(result.rows) == 2
    assert all(row.asset_type == "CfdOnIndex" for row in result.rows)
    assert all(row.minimum_trade_size == 0.01 for row in result.rows)
    assert all(row.zero_commission_both_sides is True for row in result.rows)
