from __future__ import annotations

from saxo_provider import SaxoInstrument
from trading_desk_products import (
    LEVERAGED_ASSET_TYPES,
    LeveragedProduct,
    discover_leveraged_products,
    product_details,
    product_label,
)


class _FakeClient:
    def __init__(self) -> None:
        self.search_calls: list[tuple[str, str]] = []
        self.details_calls: list[tuple[int, str]] = []

    def search_instruments(self, keywords: str, *, asset_types: str):
        self.search_calls.append((keywords, asset_types))
        if keywords == "Gold":
            return [
                SaxoInstrument(
                    asset=keywords,
                    uic=11,
                    asset_type="WarrantOpenEndKnockOut",
                    symbol="GOLD LONG",
                    description="Gold Mini Long",
                ),
                SaxoInstrument(
                    asset=keywords,
                    uic=12,
                    asset_type="MiniFuture",
                    symbol="GOLD SHORT",
                    description="Gold Mini Short",
                ),
                SaxoInstrument(
                    asset=keywords,
                    uic=13,
                    asset_type="Stock",
                    symbol="GOLD",
                    description="Gold stock",
                ),
            ]
        if keywords == "XAU":
            return [
                SaxoInstrument(
                    asset=keywords,
                    uic=11,
                    asset_type="WarrantOpenEndKnockOut",
                    symbol="GOLD LONG",
                    description="Gold Mini Long",
                ),
                SaxoInstrument(
                    asset=keywords,
                    uic=14,
                    asset_type="WarrantOtherLeverageWithKnockOut",
                    symbol="XAU TURBO BULL",
                    description="XAU Turbo Bull",
                ),
            ]
        if keywords == "XAUUSD":
            return [
                SaxoInstrument(
                    asset=keywords,
                    uic=15,
                    asset_type="WarrantDoubleKnockOut",
                    symbol="XAU DKO BEAR",
                    description="XAU Double KnockOut Bear",
                )
            ]
        return []

    def instrument_details(self, instrument: SaxoInstrument):
        self.details_calls.append((instrument.uic, instrument.asset_type))
        return {
            "Direction": "Long",
            "IsTradable": True,
            "CurrencyCode": "EUR",
            "FinancingLevel": 3890.5,
            "DefaultAmount": 100,
            "OptionData": {"LowerBarrier": 3910.0, "Strike": 3890.5},
        }


def test_discovery_uses_market_aliases_supported_knockout_types_and_deduplicates() -> None:
    client = _FakeClient()

    products = discover_leveraged_products(client, "Gold")

    assert client.search_calls == [
        ("Gold", LEVERAGED_ASSET_TYPES),
        ("XAU", LEVERAGED_ASSET_TYPES),
        ("XAUUSD", LEVERAGED_ASSET_TYPES),
    ]
    assert [(item.instrument.uic, item.direction) for item in products] == [
        (14, "Long"),
        (11, "Long"),
        (15, "Short"),
        (12, "Short"),
    ]
    assert "WarrantOtherLeverageWithKnockOut" in LEVERAGED_ASSET_TYPES
    assert "WarrantDoubleKnockOut" in LEVERAGED_ASSET_TYPES


def test_unknown_market_does_not_call_saxo() -> None:
    client = _FakeClient()

    assert discover_leveraged_products(client, "Unknown") == ()
    assert client.search_calls == []


def test_product_details_preserve_exact_uic_asset_type_and_risk_fields() -> None:
    client = _FakeClient()
    product = LeveragedProduct(
        instrument=SaxoInstrument(
            asset="Gold",
            uic=11,
            asset_type="WarrantOpenEndKnockOut",
            symbol="GOLD LONG",
            description="Gold Mini Long",
        ),
        direction="Long",
    )

    details = product_details(client, product)

    assert client.details_calls == [(11, "WarrantOpenEndKnockOut")]
    assert details.instrument.uic == 11
    assert details.instrument.asset_type == "WarrantOpenEndKnockOut"
    assert details.direction == "Long"
    assert details.is_tradable is True
    assert details.currency == "EUR"
    assert details.barrier == 3910.0
    assert details.financing_level == 3890.5
    assert details.strike == 3890.5
    assert details.default_amount == 100.0


def test_product_label_makes_direction_and_instrument_identity_explicit() -> None:
    product = LeveragedProduct(
        instrument=SaxoInstrument(
            asset="Gold",
            uic=42,
            asset_type="MiniFuture",
            symbol="TEST",
            description="Gold Long",
        ),
        direction="Long",
    )

    label = product_label(product)

    assert "Long" in label
    assert "Gold Long" in label
    assert "MiniFuture" in label
    assert "UIC 42" in label
