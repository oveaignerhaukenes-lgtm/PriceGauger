from __future__ import annotations

import pytest

from saxo_provider import SaxoInstrument
from trading_desk_order_preview import build_order_preview
from trading_desk_products import LeveragedProduct


def _product(direction: str | None = "Long") -> LeveragedProduct:
    return LeveragedProduct(
        instrument=SaxoInstrument(
            asset="Gold",
            uic=12345,
            asset_type="MiniFuture",
            symbol="MINI GOLD L",
            description="Mini Future Long Gold",
        ),
        direction=direction,
    )


def test_build_buy_preview_keeps_exact_saxo_identity() -> None:
    preview = build_order_preview(
        market="Gold",
        product=_product("Long"),
        account_key="account-key",
        account_id="SIM-001",
        action="Buy",
        amount=2,
    )

    assert preview.market == "Gold"
    assert preview.action == "Buy"
    assert preview.action_label == "KJØP"
    assert preview.amount == 2.0
    assert preview.uic == 12345
    assert preview.asset_type == "MiniFuture"
    assert preview.account_key == "account-key"
    assert preview.account_id == "SIM-001"
    assert preview.exposure_label == "Kjøp av et Long-produkt"


def test_buying_short_product_is_described_as_short_product_exposure() -> None:
    preview = build_order_preview(
        market="Gold",
        product=_product("Short"),
        account_key="account-key",
        account_id="SIM-001",
        action="Buy",
        amount=1,
    )

    assert preview.exposure_label == "Kjøp av et Short-produkt"


def test_sell_does_not_claim_to_short_the_underlying() -> None:
    preview = build_order_preview(
        market="Gold",
        product=_product("Long"),
        account_key="account-key",
        account_id="SIM-001",
        action="Sell",
        amount=1,
    )

    assert preview.action_label == "SELG"
    assert "posisjonseffekt avhenger" in preview.exposure_label
    assert "Short" not in preview.exposure_label


def test_preview_requires_positive_amount() -> None:
    with pytest.raises(ValueError, match="større enn 0"):
        build_order_preview(
            market="Gold",
            product=_product(),
            account_key="account-key",
            account_id="SIM-001",
            action="Buy",
            amount=0,
        )


def test_preview_requires_account_key() -> None:
    with pytest.raises(ValueError, match="account_key"):
        build_order_preview(
            market="Gold",
            product=_product(),
            account_key="",
            account_id="SIM-001",
            action="Buy",
            amount=1,
        )


def test_preview_rejects_unknown_action() -> None:
    with pytest.raises(ValueError, match="Buy eller Sell"):
        build_order_preview(
            market="Gold",
            product=_product(),
            account_key="account-key",
            account_id="SIM-001",
            action="Short",
            amount=1,
        )
