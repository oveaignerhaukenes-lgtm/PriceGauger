from __future__ import annotations

import pytest

import autotrader_open_sizing_v2 as sizing


def test_amount_precision_uses_instrument_rules():
    rules = sizing.EntryInstrumentRulesV2(
        uic=1, asset_type="CfdOnIndex", currency="NOK", is_tradable=True,
        non_tradable_reason="None", amount_decimals=2, minimum_amount=0.01,
        increment_size=0.01, contract_size=1.0, supported_order_types=("Market",), amount_quantum=0.01,
    )
    assert sizing._quantized_amount(0.109, rules, upward=False) == pytest.approx(0.10)
