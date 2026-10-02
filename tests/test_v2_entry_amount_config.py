from __future__ import annotations

from types import SimpleNamespace

import pytest

import autotrader_live_open_v2 as module
import autotrader_open_sizing_v2 as sizing


def _rules(*, minimum: float = 0.01, increment: float = 0.01):
    return sizing.EntryInstrumentRulesV2(
        uic=1,
        asset_type="CfdOnIndex",
        currency="NOK",
        is_tradable=True,
        non_tradable_reason="None",
        amount_decimals=2,
        minimum_amount=minimum,
        increment_size=increment,
        contract_size=1.0,
        supported_order_types=("Market",),
        amount_quantum=0.01,
    )


def _call(**kwargs):
    values = dict(
        account_key="acct",
        account_currency="NOK",
        instrument=SimpleNamespace(uic=1, asset_type="CfdOnIndex"),
        direction="LONG",
        envelope=object(),
        controlled_capital=500.0,
        external_reference_prefix="test",
    )
    values.update(kwargs)
    return module._find_configured_entry_v2(object(), **values)


def test_entry_amount_configuration_is_optional_and_instrument_agnostic(monkeypatch):
    monkeypatch.delenv(module.V2_ENTRY_AMOUNT_ENV, raising=False)
    assert module._configured_entry_amount_v2() is None

    for raw, expected in (("0.01", 0.01), ("0.03", 0.03), ("0.10", 0.10), ("2.50", 2.50)):
        monkeypatch.setenv(module.V2_ENTRY_AMOUNT_ENV, raw)
        assert module._configured_entry_amount_v2() == pytest.approx(expected)


def test_entry_amount_configuration_rejects_invalid_values(monkeypatch):
    for raw, reason in (("0", "positive"), ("-0.01", "positive"), ("invalid", "numeric")):
        monkeypatch.setenv(module.V2_ENTRY_AMOUNT_ENV, raw)
        with pytest.raises(sizing.EntrySizingError, match=reason):
            module._configured_entry_amount_v2()


def test_no_configuration_preserves_existing_sizing_policy(monkeypatch):
    monkeypatch.delenv(module.V2_ENTRY_AMOUNT_ENV, raising=False)
    sentinel = object()
    monkeypatch.setattr(module, "_ORIGINAL_FIND_ENTRY", lambda *a, **k: sentinel)
    assert _call() is sentinel


def test_configured_amount_uses_instrument_rules_and_precheck(monkeypatch):
    monkeypatch.setenv(module.V2_ENTRY_AMOUNT_ENV, "0.10")
    rules = _rules()
    final = SimpleNamespace(
        allowed=True,
        margin_decision=SimpleNamespace(allowed=True, reasons=()),
        notional_account=100.0,
        precheck_result="Ok",
        disclaimers_present=False,
    )
    monkeypatch.setattr(sizing, "load_entry_instrument_rules_v2", lambda *a, **k: rules)
    monkeypatch.setattr(sizing, "precheck_entry_amount_v2", lambda *a, **k: final)

    result = _call()
    assert result.amount == pytest.approx(0.10)
    assert result.precheck_count == 1


def test_configured_amount_below_instrument_minimum_is_rejected(monkeypatch):
    monkeypatch.setenv(module.V2_ENTRY_AMOUNT_ENV, "0.01")
    monkeypatch.setattr(sizing, "load_entry_instrument_rules_v2", lambda *a, **k: _rules(minimum=0.10))
    with pytest.raises(sizing.EntrySizingError, match="below Saxo minimum"):
        _call()


def test_configured_amount_surfaces_precheck_policy_reason(monkeypatch):
    monkeypatch.setenv(module.V2_ENTRY_AMOUNT_ENV, "0.10")
    monkeypatch.setattr(sizing, "load_entry_instrument_rules_v2", lambda *a, **k: _rules())
    final = SimpleNamespace(
        allowed=False,
        margin_decision=SimpleNamespace(allowed=False, reasons=("NOTIONAL_LIMIT",)),
        notional_account=1000.0,
        precheck_result="Ok",
        disclaimers_present=False,
    )
    monkeypatch.setattr(sizing, "precheck_entry_amount_v2", lambda *a, **k: final)
    with pytest.raises(sizing.EntrySizingError, match="NOTIONAL_LIMIT"):
        _call()


def test_configured_amount_keeps_explicit_scoped_notional_cap(monkeypatch):
    monkeypatch.setenv(module.V2_ENTRY_AMOUNT_ENV, "0.10")
    monkeypatch.setattr(sizing, "load_entry_instrument_rules_v2", lambda *a, **k: _rules())
    final = SimpleNamespace(
        allowed=True,
        margin_decision=SimpleNamespace(allowed=True, reasons=()),
        notional_account=1000.0,
        precheck_result="Ok",
        disclaimers_present=False,
    )
    monkeypatch.setattr(sizing, "precheck_entry_amount_v2", lambda *a, **k: final)
    with pytest.raises(sizing.EntrySizingError, match="scoped notional cap"):
        _call(max_notional_account=500.0)
