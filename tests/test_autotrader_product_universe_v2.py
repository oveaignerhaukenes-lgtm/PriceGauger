from __future__ import annotations

import pytest

from autotrader_product_universe_v2 import (
    AutoTraderProductUniverseEntryV2,
    evaluate_product_eligibility_v2,
    require_product_eligible_v2,
)
from saxo_provider import SaxoInstrument
from trading_desk_products import LeveragedProduct, LeveragedProductDetails


def _product(*, uic: int = 123, asset_type: str = "MiniFuture", direction: str = "Long") -> LeveragedProduct:
    return LeveragedProduct(
        instrument=SaxoInstrument(
            asset="Gold",
            uic=uic,
            asset_type=asset_type,
            symbol="TEST",
            description="Test product",
        ),
        direction=direction,
    )


def _details(product: LeveragedProduct, *, tradable: bool = True, direction: str = "Long") -> LeveragedProductDetails:
    return LeveragedProductDetails(
        instrument=product.instrument,
        direction=direction,
        is_tradable=tradable,
        currency="NOK",
        barrier=100.0,
        financing_level=90.0,
        strike=None,
        default_amount=1.0,
    )


def test_unknown_saxo_product_is_never_execution_eligible() -> None:
    product = _product()
    result = evaluate_product_eligibility_v2(market="Gold", product=product, universe=())
    assert result.eligible is False
    assert result.reasons == ("NOT_IN_PG_PRODUCT_UNIVERSE",)


def test_exact_curated_identity_can_become_eligible_only_when_all_hard_flags_are_verified() -> None:
    product = _product()
    entry = AutoTraderProductUniverseEntryV2(
        uic=123,
        asset_type="MiniFuture",
        market="Gold",
        direction="Long",
        enabled=True,
        limited_loss_verified=True,
        no_margin_obligation_verified=True,
        transaction_costs_verified=True,
        max_fixed_commission=0.0,
    )
    result = evaluate_product_eligibility_v2(
        market="Gold",
        product=product,
        details=_details(product),
        universe=(entry,),
    )
    assert result.eligible is True
    assert result.reasons == ()
    assert result.entry == entry


def test_missing_risk_or_cost_verification_fails_closed() -> None:
    product = _product()
    entry = AutoTraderProductUniverseEntryV2(
        uic=123,
        asset_type="MiniFuture",
        market="Gold",
        direction="Long",
        enabled=True,
        limited_loss_verified=True,
        no_margin_obligation_verified=False,
        transaction_costs_verified=False,
    )
    result = evaluate_product_eligibility_v2(
        market="Gold",
        product=product,
        universe=(entry,),
    )
    assert result.eligible is False
    assert "NO_MARGIN_OBLIGATION_NOT_VERIFIED" in result.reasons
    assert "TRANSACTION_COSTS_NOT_VERIFIED" in result.reasons


def test_market_direction_and_tradability_must_match_curated_contract() -> None:
    product = _product(direction="Short")
    entry = AutoTraderProductUniverseEntryV2(
        uic=123,
        asset_type="MiniFuture",
        market="Silver",
        direction="Long",
        enabled=True,
        limited_loss_verified=True,
        no_margin_obligation_verified=True,
        transaction_costs_verified=True,
    )
    result = evaluate_product_eligibility_v2(
        market="Gold",
        product=product,
        details=_details(product, tradable=False, direction="Short"),
        universe=(entry,),
    )
    assert result.eligible is False
    assert "MARKET_MISMATCH" in result.reasons
    assert "DIRECTION_MISMATCH" in result.reasons
    assert "NOT_TRADABLE" in result.reasons


def test_verified_margin_product_still_requires_active_margin_envelope() -> None:
    product = _product(asset_type="CfdOnFutures", direction="Long")
    entry = AutoTraderProductUniverseEntryV2(
        uic=123,
        asset_type="CfdOnFutures",
        market="Gold",
        direction="Both",
        enabled=True,
        transaction_costs_verified=True,
        margin_product_allowed=True,
        negative_balance_protection_verified=True,
    )

    blocked = evaluate_product_eligibility_v2(
        market="Gold",
        product=product,
        universe=(entry,),
    )
    assert blocked.eligible is False
    assert "MARGIN_ENVELOPE_NOT_ACTIVE" in blocked.reasons

    allowed = evaluate_product_eligibility_v2(
        market="Gold",
        product=product,
        universe=(entry,),
        margin_envelope_active=True,
    )
    assert allowed.eligible is True
    assert allowed.reasons == ()
    assert entry.hard_eligible is True


def test_margin_product_fails_without_negative_balance_protection_verification() -> None:
    product = _product(asset_type="FxSpot", direction="Short")
    entry = AutoTraderProductUniverseEntryV2(
        uic=123,
        asset_type="FxSpot",
        market="Gold",
        direction="Both",
        enabled=True,
        transaction_costs_verified=True,
        margin_product_allowed=True,
        negative_balance_protection_verified=False,
    )
    result = evaluate_product_eligibility_v2(
        market="Gold",
        product=product,
        universe=(entry,),
        margin_envelope_active=True,
    )
    assert result.eligible is False
    assert "NEGATIVE_BALANCE_PROTECTION_NOT_VERIFIED" in result.reasons
    assert entry.hard_eligible is False


def test_both_direction_contract_accepts_long_or_short_for_same_margin_instrument() -> None:
    entry = AutoTraderProductUniverseEntryV2(
        uic=123,
        asset_type="CfdOnFutures",
        market="Gold",
        direction="Both",
        enabled=True,
        transaction_costs_verified=True,
        margin_product_allowed=True,
        negative_balance_protection_verified=True,
    )
    for direction in ("Long", "Short"):
        product = _product(asset_type="CfdOnFutures", direction=direction)
        result = evaluate_product_eligibility_v2(
            market="Gold",
            product=product,
            universe=(entry,),
            margin_envelope_active=True,
        )
        assert result.eligible is True
        assert "DIRECTION_MISMATCH" not in result.reasons


def test_duplicate_curated_identity_is_rejected() -> None:
    product = _product()
    one = AutoTraderProductUniverseEntryV2(
        uic=123,
        asset_type="MiniFuture",
        market="Gold",
        direction="Long",
    )
    two = AutoTraderProductUniverseEntryV2(
        uic=123,
        asset_type="MiniFuture",
        market="Silver",
        direction="Short",
    )
    with pytest.raises(ValueError, match="duplicate AutoTrader product identity"):
        evaluate_product_eligibility_v2(
            market="Gold",
            product=product,
            universe=(one, two),
        )


def test_require_product_eligible_fails_with_explicit_reason() -> None:
    product = _product()
    with pytest.raises(ValueError, match="NOT_IN_PG_PRODUCT_UNIVERSE"):
        require_product_eligible_v2(market="Gold", product=product, universe=())
