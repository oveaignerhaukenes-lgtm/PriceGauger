from __future__ import annotations

from types import SimpleNamespace

import pytest

import autotrader_live_open_v2 as module
import autotrader_open_sizing_v2 as sizing


def test_configured_amount_below_instrument_minimum_is_rejected(monkeypatch):
    monkeypatch.setenv(module.V2_ENTRY_AMOUNT_ENV, "0.01")
    rules = sizing.EntryInstrumentRulesV2(
        uic=1,
        asset_type="CfdOnIndex",
        currency="NOK",
        is_tradable=True,
        non_tradable_reason="None",
        amount_decimals=2,
        minimum_amount=0.10,
        increment_size=0.01,
        contract_size=1.0,
        supported_order_types=("Market",),
        amount_quantum=0.01,
    )
    monkeypatch.setattr(sizing, "load_entry_instrument_rules_v2", lambda *a, **k: rules)
    with pytest.raises(sizing.EntrySizingError, match="below Saxo minimum"):
        module._find_configured_entry_v2(
            object(),
            account_key="acct",
            account_currency="NOK",
            instrument=SimpleNamespace(uic=1, asset_type="CfdOnIndex"),
            direction="LONG",
            envelope=object(),
            controlled_capital=500.0,
            external_reference_prefix="test",
        )
