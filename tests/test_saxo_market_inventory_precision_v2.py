from saxo_market_inventory_v2 import (
    MARKET_INVENTORY_PRECISE_TERMS,
    SaxoMarketInventoryResultV2,
    SaxoMarketInventoryRowV2,
    precise_asset_type_rows_for_ui_v2,
    precise_market_rows_v2,
)


def _row(identifier, asset_type, *queries):
    return SaxoMarketInventoryRowV2(
        account_label="…2345 NOK",
        matched_queries=tuple(queries),
        identifier=identifier,
        asset_type=asset_type,
        summary_type="Instrument",
        description=f"row-{identifier}",
        symbol=f"S{identifier}",
        exchange_id=None,
        exchange_name=None,
        currency="USD",
        tradable_as=(asset_type,),
        underlying_asset_type=None,
        non_tradable_reason=None,
        group_id=None,
        primary_listing=None,
    )


def test_gold_generic_keyword_is_recall_only():
    assert "Gold" not in MARKET_INVENTORY_PRECISE_TERMS["Gold"]
    assert {"XAU", "XAUUSD", "Gold Spot"}.issubset(set(MARKET_INVENTORY_PRECISE_TERMS["Gold"]))


def test_precise_rows_exclude_generic_gold_noise_but_keep_overlap():
    result = SaxoMarketInventoryResultV2(
        market="Gold",
        rows=(
            _row(1, "Stock", "Gold"),
            _row(2, "FxSpot", "XAUUSD"),
            _row(3, "Etc", "Gold", "XAU"),
        ),
        queries=(),
        account_labels=("…2345 NOK",),
        asset_type_counts=(("Stock", 1), ("FxSpot", 1), ("Etc", 1)),
    )
    rows = precise_market_rows_v2(result)
    assert {row.identifier for row in rows} == {2, 3}


def test_precise_asset_type_counts_are_based_on_precise_rows_only():
    result = SaxoMarketInventoryResultV2(
        market="Gold",
        rows=(
            _row(1, "Stock", "Gold"),
            _row(2, "FxSpot", "XAUUSD"),
            _row(3, "FxSpot", "XAU"),
            _row(4, "Etc", "Gold Spot"),
        ),
        queries=(),
        account_labels=(),
        asset_type_counts=(),
    )
    counts = precise_asset_type_rows_for_ui_v2(result)
    assert counts == [
        {"AssetType": "FxSpot", "Presise treff": 2},
        {"AssetType": "Etc", "Presise treff": 1},
    ]
