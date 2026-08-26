from saxo_low_friction_candidates_v2 import (
    low_friction_rows_for_ui_v2,
    scan_low_friction_margin_candidates_v2,
)
from saxo_market_inventory_v2 import (
    SaxoMarketInventoryQueryV2,
    SaxoMarketInventoryResultV2,
    SaxoMarketInventoryRowV2,
)


class FakeClient:
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
        if path.startswith("cs/v1/tradingconditions/cost/"):
            uic = int(path.split("/")[-2])
            if uic == 101:
                return {
                    "AccountCurrency": "NOK",
                    "Cost": {
                        "Long": {
                            "Currency": "NOK",
                            "TotalCostPct": 0.12,
                            "TradingCost": {},
                        },
                        "Short": {
                            "Currency": "NOK",
                            "TotalCostPct": 0.13,
                            "TradingCost": {},
                        },
                    },
                }
            return {
                "AccountCurrency": "NOK",
                "Cost": {
                    "Long": {
                        "Currency": "NOK",
                        "TotalCostPct": 0.4,
                        "TradingCost": {"Commissions": [{"Value": 5.0}]},
                    },
                    "Short": {
                        "Currency": "NOK",
                        "TotalCostPct": 0.4,
                        "TradingCost": {"Commissions": [{"Value": 5.0}]},
                    },
                },
            }
        raise AssertionError(path)

    def info_price(self, instrument):
        if instrument.uic == 101:
            return {"Quote": {"Bid": 2500.0, "Ask": 2500.2}}
        return {"Quote": {"Bid": 88.0, "Ask": 88.1}}

    def instrument_details(self, instrument):
        return {
            "MinimumTradeSize": 0.01,
            "IncrementSize": 0.01,
            "InitialMarginPercent": 7.0 if instrument.uic == 101 else 10.0,
        }


def _row(identifier, asset_type, description, symbol, query):
    return SaxoMarketInventoryRowV2(
        account_label="…2345 NOK",
        matched_queries=(query,),
        identifier=identifier,
        asset_type=asset_type,
        summary_type="Instrument",
        description=description,
        symbol=symbol,
        exchange_id=None,
        exchange_name=None,
        currency="USD",
        tradable_as=(asset_type,),
        underlying_asset_type=None,
        non_tradable_reason=None,
        group_id=None,
        primary_listing=None,
    )


def _inventory():
    rows = (
        _row(101, "FxSpot", "Gold / US Dollar", "XAUUSD", "XAUUSD"),
        _row(202, "CfdOnFutures", "Brent CFD", "OILUK", "Gold Spot"),
        _row(303, "Stock", "Gold Fields Ltd", "GFI", "Gold"),
    )
    return SaxoMarketInventoryResultV2(
        market="Gold",
        rows=rows,
        queries=(
            SaxoMarketInventoryQueryV2("…2345 NOK", "XAUUSD", 1),
            SaxoMarketInventoryQueryV2("…2345 NOK", "Gold Spot", 1),
            SaxoMarketInventoryQueryV2("…2345 NOK", "Gold", 1),
        ),
        account_labels=("…2345 NOK",),
        asset_type_counts=(("FxSpot", 1), ("CfdOnFutures", 1), ("Stock", 1)),
    )


def test_scanner_accepts_margin_families_but_not_broad_stock_noise():
    result = scan_low_friction_margin_candidates_v2(FakeClient(), inventory=_inventory())

    assert result.precise_rows_seen == 2
    assert result.candidate_rows_seen == 2
    assert {row.asset_type for row in result.rows} == {"FxSpot", "CfdOnFutures"}
    assert all(row.provisional_margin_candidate for row in result.rows)


def test_zero_commission_both_sides_is_ranked_first_and_spread_is_measured():
    result = scan_low_friction_margin_candidates_v2(FakeClient(), inventory=_inventory())

    first = result.rows[0]
    assert first.uic == 101
    assert first.zero_commission_both_sides is True
    assert first.long_commission == 0.0
    assert first.short_commission == 0.0
    assert first.spread_pct is not None
    assert first.margin_requirement_pct == 7.0


def test_margin_research_assumption_never_grants_live_execution():
    result = scan_low_friction_margin_candidates_v2(FakeClient(), inventory=_inventory())
    ui_rows = low_friction_rows_for_ui_v2(result.rows)

    assert all(row.live_execution_eligible is False for row in result.rows)
    assert all(item["LIVE eligible"] is False for item in ui_rows)
