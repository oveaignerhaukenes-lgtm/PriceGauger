from pathlib import Path

from autotrader_product_scanner_v2 import (
    ProductScanRowV2,
    SCANNER_MARKET_SEARCH_TERMS,
    SCANNER_STRUCTURED_ASSET_TYPES,
    SaxoScannerAccountV2,
    _cost_illustration_v2,
    _quote_fields,
    _sum_commissions,
    candidate_rows_for_ui_v2,
)
from saxo_provider import SaxoInstrument
from trading_desk_products import LeveragedProduct, LeveragedProductDetails


def test_quote_fields_computes_relative_spread_from_bid_ask():
    bid, ask, mid, spread = _quote_fields({"Quote": {"Bid": 99.0, "Ask": 101.0}})
    assert bid == 99.0
    assert ask == 101.0
    assert mid == 100.0
    assert spread == 0.02


def test_quote_fields_does_not_invent_spread_when_one_side_missing():
    bid, ask, mid, spread = _quote_fields({"Quote": {"Bid": 99.0}})
    assert bid == 99.0
    assert ask is None
    assert mid is None
    assert spread is None


def test_candidate_ui_keeps_cost_and_pg_eligibility_explicit():
    row = ProductScanRowV2(
        market="Gold",
        uic=123,
        asset_type="MiniFuture",
        description="Test Mini Long",
        direction="Long",
        currency="EUR",
        exchange="CATS",
        is_tradable=True,
        bid=1.0,
        ask=1.01,
        mid=1.005,
        spread_pct=(1.01 - 1.0) / 1.005,
        minimum_trade_size=1.0,
        minimum_trade_value=1.01,
        increment_size=1.0,
        barrier=4200.0,
        financing_level=4190.0,
        commission_cost=0.0,
        commission_currency="EUR",
        zero_commission=True,
        total_cost_pct=0.25,
        cost_assumptions=("IncludesOpenAndCloseCost",),
        cost_error=None,
        in_pg_universe=False,
        pg_eligible=False,
        eligibility_reasons=("NOT_IN_PG_PRODUCT_UNIVERSE",),
        scan_error=None,
    )
    rendered = candidate_rows_for_ui_v2((row,))[0]
    assert rendered["Børs"] == "CATS"
    assert rendered["0 kommisjon*"] is True
    assert rendered["Kommisjon*"] == 0.0
    assert rendered["I PG-univers"] is False
    assert rendered["AutoTrader eligible"] is False
    assert rendered["Blokkert fordi"] == "NOT_IN_PG_PRODUCT_UNIVERSE"
    assert rendered["Spread %"] > 0


def test_scanner_market_aliases_cover_saxo_oil_and_structured_families():
    assert "Oil" in SCANNER_MARKET_SEARCH_TERMS["Brent"]
    assert "UKOIL" in SCANNER_MARKET_SEARCH_TERMS["Brent"]
    assert "MiniFuture" in SCANNER_STRUCTURED_ASSET_TYPES
    assert "WarrantOpenEndKnockOut" in SCANNER_STRUCTURED_ASSET_TYPES
    assert "WarrantOtherLeverageWithKnockOut" in SCANNER_STRUCTURED_ASSET_TYPES


def test_sum_commissions_is_explicit_and_additive():
    assert _sum_commissions({"Commissions": [{"Value": 2.0}, {"Value": 0.5}]}) == 2.5
    assert _sum_commissions({"Commissions": []}) == 0.0
    assert _sum_commissions({}) == 0.0


class _CostClient:
    def __init__(self):
        self.calls = []

    def _get(self, path, params=None):
        self.calls.append((path, dict(params or {})))
        assert path.startswith("cs/v1/tradingconditions/cost/")
        return {
            "AccountCurrency": "NOK",
            "Cost": {
                "Long": {
                    "Currency": "EUR",
                    "TotalCostPct": 0.18,
                    "TradingCost": {"Commissions": []},
                }
            },
            "CostCalculationAssumptions": ["IncludesOpenAndCloseCost"],
        }


def test_cost_illustration_uses_read_only_saxo_cost_endpoint_and_client_context():
    instrument = SaxoInstrument(asset="Gold", uic=123, asset_type="MiniFuture", description="Gold Mini Long")
    product = LeveragedProduct(instrument=instrument, direction="Long")
    details = LeveragedProductDetails(
        instrument=instrument,
        direction="Long",
        is_tradable=True,
        currency="EUR",
        barrier=4000.0,
        financing_level=3990.0,
        strike=None,
        default_amount=1.0,
        minimum_trade_size=1.0,
        increment_size=1.0,
    )
    account = SaxoScannerAccountV2(account_key="abc|def==", account_id="12345678", currency="NOK")
    client = _CostClient()

    commission, currency, zero, total_pct, assumptions, error = _cost_illustration_v2(
        client,
        account=account,
        product=product,
        details=details,
        price=2.5,
    )

    assert error is None
    assert commission == 0.0
    assert currency == "EUR"
    assert zero is True
    assert total_pct == 0.18
    assert assumptions == ("IncludesOpenAndCloseCost",)
    assert client.calls[0][1]["TradeContext"] == "ClientTrading"
    assert client.calls[0][1]["HoldingPeriodInDays"] == 1


def test_scanner_ui_does_not_depend_on_sim_only_trading_adapter_or_order_execution():
    source = Path("autotrader_product_scanner_ui_v2.py").read_text(encoding="utf-8")
    scanner_source = Path("autotrader_product_scanner_v2.py").read_text(encoding="utf-8")
    assert "configured_client" in source
    assert "configured_trading_client" not in source
    assert "SaxoTradingSafetyError" not in source
    assert "place_order" not in scanner_source
    assert "trade/v2/orders" not in scanner_source
    assert "cs/v1/tradingconditions/cost/" in scanner_source
