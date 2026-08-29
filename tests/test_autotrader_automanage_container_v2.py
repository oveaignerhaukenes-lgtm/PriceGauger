from __future__ import annotations

from types import SimpleNamespace

from autotrader_automanage_container_v2 import AutoManageProductV2, resolve_saxo_automanage_product_v2
from autotrader_strategy_catalog_v2 import MACD_LONG_FLAT_STRATEGY_V2
from autotrader_macd_flip_policy_v2 import MACD_FLIP_STRATEGY_V2


def _product() -> AutoManageProductV2:
    return AutoManageProductV2(
        provider="saxo",
        account_id="ACC-1",
        anchor_position_id="NET-1",
        provider_instrument_id="12345",
        asset_type="CfdOnIndex",
        market_id=7,
        market_name="Australia Tech",
        instrument_id=11,
    )


def test_product_container_is_strategy_neutral_and_strategies_get_distinct_pilot_keys():
    product = _product()
    assert product.product_key
    assert product.pilot_key(MACD_FLIP_STRATEGY_V2) != product.pilot_key(MACD_LONG_FLAT_STRATEGY_V2)
    assert product.source_fingerprint == "saxo|12345|CfdOnIndex|11|7|Australia Tech"


def test_existing_flip_key_shape_is_preserved_for_saxo():
    from uuid import NAMESPACE_URL, uuid5

    product = _product()
    expected = str(uuid5(NAMESPACE_URL, f"{MACD_FLIP_STRATEGY_V2}|ACC-1|12345|CfdOnIndex"))
    assert product.pilot_key(MACD_FLIP_STRATEGY_V2) == expected


def test_any_subscribed_saxo_uic_asset_type_can_resolve(monkeypatch):
    observation = SimpleNamespace(
        account_id="ACC-2",
        net_position_id="NET-X",
        uic=987654,
        asset_type="Stock",
    )
    source = SimpleNamespace(
        market_id=42,
        market_name="Example Equity",
        instrument_id=84,
        asset_type="Stock",
    )
    monkeypatch.setattr(
        "autotrader_automanage_container_v2.resolve_instrument_source_v2",
        lambda **kwargs: source,
    )
    product = resolve_saxo_automanage_product_v2(observation)
    assert product.provider_instrument_id == "987654"
    assert product.asset_type == "Stock"
    assert product.market_id == 42
    assert product.instrument_id == 84
