from __future__ import annotations

import pytest

import autotrader_open_sizing_v2 as sizing
from autotrader_entry_sizing_policy_v2 import (
    EntrySizingPolicyV2,
    SIZING_MODE_FIXED,
    SIZING_MODE_MAX,
)
from autotrader_margin_envelope_v2 import AutoTraderMarginEnvelopeV2
from autotrader_open_sizing_v2 import (
    EntrySizingError,
    find_largest_legal_entry_v2,
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
            request = dict(params or {})
            self.info_price_params.append(request)
            payload = dict(self.info_price)
            quote = dict(payload.get("Quote") or {})
            if "Amount" in request:
                quote["Amount"] = float(request["Amount"])
            payload["Quote"] = quote
            return payload
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


@pytest.fixture(autouse=True)
def _default_max_sizing_policy(monkeypatch):
    def load_default(**kwargs):
        return EntrySizingPolicyV2(
            account_key=str(kwargs["account_key"]),
            uic=int(kwargs["uic"]),
            asset_type=str(kwargs["asset_type"]),
            direction=str(kwargs["direction"]).upper(),
            sizing_mode=SIZING_MODE_MAX,
            fixed_amount=None,
        )

    monkeypatch.setattr(sizing, "load_entry_sizing_policy_v2", load_default)


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


def test_explicit_reference_minimum_is_a_hard_floor():
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
    assert resolution.amount == pytest.approx(1.0)
    assert resolution.reference_minimum_amount == pytest.approx(1.0)
    assert resolution.source == "SAXO_REFERENCE_AND_INFOPRICE_MINIMUM"


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


def _fractional_precheck(payload: dict, *, available: float = 500.0):
    amount = float(payload["Amount"])
    margin = 13_795.0 * amount
    return {
        "PreCheckResult": "Ok",
        "MarginImpactBuySell": {
            "Currency": "USD",
            "InitialMarginBuy": margin,
            "InitialMarginAvailableCurrent": available,
            "InitialMarginAvailableBuy": max(0.0, available - margin),
        },
        "EstimatedTotalCostInAccountCurrency": 0.0,
    }


def _pilot_envelope() -> AutoTraderMarginEnvelopeV2:
    return AutoTraderMarginEnvelopeV2(
        currency="USD",
        capital_control_limit=500.0,
        max_initial_margin=500.0,
        max_notional_exposure=10_000.0,
        max_effective_leverage=20.0,
        minimum_free_capital=0.0,
        enabled=True,
    )


def test_margin_envelope_can_select_point_zero_three_from_fractional_cfd(monkeypatch):
    client = _FakeSaxoClient(
        details=_base_details(),
        info_price={
            "Quote": {
                "Amount": 0.01,
                "Ask": 276_588.0,
                "Bid": 276_580.0,
            }
        },
    )

    def fake_precheck(_client, path: str, payload: dict):
        assert path == "trade/v2/orders/precheck"
        return _fractional_precheck(payload)

    monkeypatch.setattr(sizing, "_post_once", fake_precheck)

    result = find_largest_legal_entry_v2(
        client,
        account_key="account-key",
        account_currency="USD",
        instrument=_instrument(),
        direction="LONG",
        envelope=_pilot_envelope(),
        controlled_capital=500.0,
        external_reference_prefix="test-fractional",
    )

    assert result.rules.increment_size == pytest.approx(0.01)
    assert result.amount == pytest.approx(0.03)
    assert result.final_precheck.initial_margin_account == pytest.approx(413.85)
    assert result.final_precheck.notional_account == pytest.approx(8_297.64)


def test_fixed_amount_policy_uses_exact_amount_and_does_not_search(monkeypatch):
    client = _FakeSaxoClient(
        details=_base_details(),
        info_price={
            "Quote": {
                "Amount": 0.01,
                "Ask": 276_588.0,
                "Bid": 276_580.0,
            }
        },
    )
    monkeypatch.setattr(
        sizing,
        "load_entry_sizing_policy_v2",
        lambda **_: EntrySizingPolicyV2(
            account_key="account-key",
            uic=4912,
            asset_type="CfdOnIndex",
            direction="LONG",
            sizing_mode=SIZING_MODE_FIXED,
            fixed_amount=0.02,
        ),
    )
    submitted_amounts: list[float] = []

    def fake_precheck(_client, path: str, payload: dict):
        assert path == "trade/v2/orders/precheck"
        submitted_amounts.append(float(payload["Amount"]))
        return _fractional_precheck(payload)

    monkeypatch.setattr(sizing, "_post_once", fake_precheck)

    result = find_largest_legal_entry_v2(
        client,
        account_key="account-key",
        account_currency="USD",
        instrument=_instrument(),
        direction="LONG",
        envelope=_pilot_envelope(),
        controlled_capital=500.0,
        external_reference_prefix="test-fixed",
    )

    assert result.amount == pytest.approx(0.02)
    assert result.precheck_count == 1
    assert submitted_amounts == [pytest.approx(0.02)]


def test_fixed_amount_policy_blocks_instead_of_silently_resizing(monkeypatch):
    client = _FakeSaxoClient(
        details=_base_details(),
        info_price={
            "Quote": {
                "Amount": 0.01,
                "Ask": 276_588.0,
                "Bid": 276_580.0,
            }
        },
    )
    monkeypatch.setattr(
        sizing,
        "load_entry_sizing_policy_v2",
        lambda **_: EntrySizingPolicyV2(
            account_key="account-key",
            uic=4912,
            asset_type="CfdOnIndex",
            direction="LONG",
            sizing_mode=SIZING_MODE_FIXED,
            fixed_amount=0.04,
        ),
    )

    def fake_precheck(_client, path: str, payload: dict):
        assert path == "trade/v2/orders/precheck"
        return _fractional_precheck(payload)

    monkeypatch.setattr(sizing, "_post_once", fake_precheck)

    with pytest.raises(EntrySizingError, match="fixed amount does not pass"):
        find_largest_legal_entry_v2(
            client,
            account_key="account-key",
            account_currency="USD",
            instrument=_instrument(),
            direction="LONG",
            envelope=_pilot_envelope(),
            controlled_capital=500.0,
            external_reference_prefix="test-fixed-block",
        )
