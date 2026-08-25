from pathlib import Path

from autotrader_product_scanner_v2 import _quote_fields, candidate_rows_for_ui_v2
from autotrader_product_scanner_v2 import ProductScanRowV2


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


def test_candidate_ui_keeps_pg_eligibility_and_scan_error_explicit():
    row = ProductScanRowV2(
        market="Gold",
        uic=123,
        asset_type="MiniFuture",
        description="Test Mini Long",
        direction="Long",
        currency="EUR",
        is_tradable=True,
        bid=1.0,
        ask=1.01,
        mid=1.005,
        spread_pct=(1.01 - 1.0) / 1.005,
        minimum_trade_size=1.0,
        increment_size=1.0,
        barrier=4200.0,
        financing_level=4190.0,
        in_pg_universe=False,
        pg_eligible=False,
        eligibility_reasons=("NOT_IN_PG_PRODUCT_UNIVERSE",),
        scan_error=None,
    )
    rendered = candidate_rows_for_ui_v2((row,))[0]
    assert rendered["I PG-univers"] is False
    assert rendered["AutoTrader eligible"] is False
    assert rendered["Blokkert fordi"] == "NOT_IN_PG_PRODUCT_UNIVERSE"
    assert rendered["Spread %"] > 0


def test_scanner_ui_does_not_depend_on_sim_only_trading_adapter():
    source = Path("autotrader_product_scanner_ui_v2.py").read_text(encoding="utf-8")
    assert "configured_client" in source
    assert "configured_trading_client" not in source
    assert "SaxoTradingSafetyError" not in source
