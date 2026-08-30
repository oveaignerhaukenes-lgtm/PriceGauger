from __future__ import annotations

import pytest

from autotrader_open_sizing_v2 import (
    load_entry_instrument_rules_v2,
    resolve_minimum_entry_amount_v2,
)
from saxo_provider import SaxoInstrument


class _FakeSaxoClient:
    def __init__(self, *, details: dict, info_price: dict):
        self.details = dict(details)
        self.info_price = dict(info_price)
        self.info_price_params: list[dict] = []

    def _get(self, path: str, params: dict | None = None):
        if path.startswith("ref/v1/instruments/details/"):
            return dict(self.details)
        if path == "trade/v1/infoprices":
            self.info_price_params.append(dict(params or {}))
            return dict(self.info_price)
        raise AssertionError(f"unexpected Saxo GET: {path}")


def _instrument() -> SaxoInstrument:
    return SaxoInstrument(asset="US Tech 100 NAS", uic=4912, asset_type="CfdOnIndex")


def _base_details(**overrides):
    payload = {
        "AssetType": "CfdOnIndex",
        "IsTradable": True,
        "NonTradableReason": "None",
        "AmountDecimals": 2,
        "DefaultAmount": 1,
        "IncrementSize": 1,
        "ContractSize": 1,
        "CurrencyCode": "USD",
        "SupportedOrderTypes": ["Market"],
    }
    payload.update(overrides)
    return payload


def test_default_amount_and_price_increment_are_not_amount_minimums():
    client = _FakeSaxoClient(
        details=_base_details(),
        info_price={"Quote": {"Amount": 0.01}},
    )

    rules = load_entry_instrument_rules_v2(
        client,
        account_key="account-key",
        instrument=_instrument(),
    )
    resolution = resolve_minimum_entry_amount_v2(
        client,
        account_key="account-key",
        instrument=_instrument(),
        rules=rules,
    )

    assert rules.amount_quantum == pytest.approx(0.01)
    assert rules.increment_size == pytest.approx(0.01)
    assert rules.minimum_amount == pytest.approx(0.01)
    assert rules.reference_minimum_amount is None
    assert resolution.amount == pytest.approx(0.01)
    assert resolution.source == "SAXO_INFOPRICE_DEFAULT_MINIMUM"
    assert "Amount" not in client.info_price_params[-1]


def test_account_specific_infoprice_can_resolve_below_reference_minimum():
    client = _FakeSaxoClient(
        details=_base_details(MinimumTradeSize=1),
        info_price={"Quote": {"Amount": 0.01}},
    )

    rules = load_entry_instrument_rules_v2(
        client,
        account_key="account-key",
        instrument=_instrument(),
    )
    resolution = resolve_minimum_entry_amount_v2(
        client,
        account_key="account-key",
        instrument=_instrument(),
        rules=rules,
    )

    assert rules.reference_minimum_amount == pytest.approx(1.0)
    assert resolution.amount == pytest.approx(0.01)
    assert resolution.reference_minimum_amount == pytest.approx(1.0)


def test_odd_lot_restriction_uses_lot_size_as_amount_step():
    client = _FakeSaxoClient(
        details=_base_details(
            AmountDecimals=0,
            MinimumLotSize=100,
            LotSize=100,
            LotSizeType="OddLotsNotAllowed",
            IncrementSize=0.01,
        ),
        info_price={"Quote": {"Amount": 100}},
    )

    rules = load_entry_instrument_rules_v2(
        client,
        account_key="account-key",
        instrument=_instrument(),
    )
    resolution = resolve_minimum_entry_amount_v2(
        client,
        account_key="account-key",
        instrument=_instrument(),
        rules=rules,
    )

    assert rules.increment_size == pytest.approx(100.0)
    assert rules.reference_minimum_amount == pytest.approx(100.0)
    assert resolution.amount == pytest.approx(100.0)


def test_minimum_order_value_is_preserved_for_audit_but_precheck_remains_authoritative():
    client = _FakeSaxoClient(
        details=_base_details(MinimumOrderValue=50),
        info_price={"Quote": {"Amount": 0.02}},
    )

    rules = load_entry_instrument_rules_v2(
        client,
        account_key="account-key",
        instrument=_instrument(),
    )
    resolution = resolve_minimum_entry_amount_v2(
        client,
        account_key="account-key",
        instrument=_instrument(),
        rules=rules,
    )

    assert rules.minimum_order_value == pytest.approx(50.0)
    assert resolution.minimum_order_value == pytest.approx(50.0)
    assert resolution.amount == pytest.approx(0.02)
