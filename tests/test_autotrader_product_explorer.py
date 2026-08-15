from __future__ import annotations

from autotrader_product_explorer import (
    CATEGORY_ASSET_TYPES,
    ProductSearchRequest,
    category_for_asset_type,
    detail_rows,
    direction_from_text,
    load_product_details,
    product_explanation,
    search_product_universe,
)
from saxo_provider import SaxoInstrument


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object] | None]] = []

    def _get(self, path: str, *, params=None):
        self.calls.append((path, dict(params) if params is not None else None))
        if path == "ref/v1/instruments":
            return {
                "Data": [
                    {
                        "Identifier": 101,
                        "AssetType": "MiniFuture",
                        "Symbol": "GOLD MINI LONG",
                        "Description": "Gold Mini Long",
                        "CurrencyCode": "EUR",
                        "ExchangeName": "Test Exchange",
                        "TradableAs": ["MiniFuture"],
                    },
                    {
                        "Identifier": 102,
                        "AssetType": "WarrantOpenEndKnockOut",
                        "Symbol": "GOLD BEAR",
                        "Description": "Gold Turbo Bear",
                        "CurrencyCode": "EUR",
                        "NonTradableReason": "NotSuitable",
                        "TradableAs": ["WarrantOpenEndKnockOut"],
                    },
                ]
            }
        return {
            "Uic": 101,
            "AssetType": "MiniFuture",
            "Description": "Gold Mini Long",
            "CurrencyCode": "EUR",
            "IsTradable": True,
            "MinimumTradeSize": 1,
            "TradableAs": ["MiniFuture"],
            "OrderSetting": {"MinOrderValue": 10},
        }


def test_category_map_includes_structured_and_extended_asset_types() -> None:
    assert "Warrant" in CATEGORY_ASSET_TYPES["Warrants / Turbo / KO"]
    assert "WarrantOpenEndKnockOut" in CATEGORY_ASSET_TYPES["Warrants / Turbo / KO"]
    assert "CertificateConstantLeverage" in CATEGORY_ASSET_TYPES["Certificates"]
    assert "CBBCCategoryR" in CATEGORY_ASSET_TYPES["Certificates"]
    assert CATEGORY_ASSET_TYPES["ETF / ETC / ETN"] == ("Etf", "Etc", "Etn")
    assert category_for_asset_type("MiniFuture") == "Mini Futures"
    assert category_for_asset_type("UnknownFutureType") == "Andre"


def test_direction_filter_is_explicit_name_interpretation() -> None:
    assert direction_from_text("Gold Mini LONG") == "Bull / Long"
    assert direction_from_text("Gold Turbo Bear") == "Bear / Short"
    assert direction_from_text("Call Warrant") == "Bull / Long"
    assert direction_from_text("Put Warrant") == "Bear / Short"
    assert direction_from_text("Gold tracker") == "Ukjent"


def test_search_passes_category_nontradable_account_and_limit_to_saxo() -> None:
    client = _FakeClient()
    request = ProductSearchRequest(
        keywords="Gold",
        category="Mini Futures",
        include_non_tradable=True,
        account_key="SIM-ACCOUNT",
        top=200,
    )

    result = search_product_universe(client, request)

    assert client.calls[0] == (
        "ref/v1/instruments",
        {
            "Keywords": "Gold",
            "IncludeNonTradable": True,
            "$top": 200,
            "AssetTypes": "MiniFuture",
            "AccountKey": "SIM-ACCOUNT",
        },
    )
    assert result.raw_count == 2
    assert [product.instrument.uic for product in result.products] == [101, 102]
    assert result.products[0].category == "Mini Futures"
    assert result.products[1].is_tradable is False


def test_direction_filter_does_not_claim_unknown_products() -> None:
    client = _FakeClient()
    result = search_product_universe(
        client,
        ProductSearchRequest(keywords="Gold", direction="Bear / Short"),
    )

    assert [product.instrument.uic for product in result.products] == [102]
    assert result.products[0].direction == "Bear / Short"


def test_detail_lookup_preserves_exact_uic_asset_type_and_account_context() -> None:
    client = _FakeClient()
    result = search_product_universe(client, ProductSearchRequest(keywords="Gold"))
    product = result.products[0]

    details = load_product_details(client, product, account_key="SIM-ACCOUNT")

    assert client.calls[-1] == (
        "ref/v1/instruments/details/101/MiniFuture",
        {"FieldGroups": "OrderSetting", "AccountKey": "SIM-ACCOUNT"},
    )
    rows = dict(detail_rows(details))
    assert rows["UIC"] == 101
    assert rows["AssetType"] == "MiniFuture"
    assert rows["Tradable"] is True
    assert rows["Min. ordreverdi"] == 10


def test_explanation_is_product_family_specific() -> None:
    client = _FakeClient()
    product = search_product_universe(client, ProductSearchRequest(keywords="Gold")).products[0]

    explanation = product_explanation(product)

    assert "Gearet" in explanation
    assert "knock-out" in explanation
