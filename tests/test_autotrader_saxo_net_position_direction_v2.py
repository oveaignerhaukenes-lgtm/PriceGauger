from __future__ import annotations

import pytest

import autotrader_risk_control_v2 as risk
from autotrader_live_close_v1 import _close_payload
from autotrader_saxo_net_position_direction_v2 import resolve_net_position_exposure_v2


def _base(**overrides):
    value = {
        "AccountId": "A1",
        "Amount": -0.03,
        "AmountLong": 0.0,
        "AmountShort": 0.03,
        "AssetType": "CfdOnIndex",
        "CanBeClosed": True,
        "IsMarketOpen": True,
        "NonTradableReason": "None",
        "OpeningDirection": "Sell",
        "SinglePositionStatus": "Open",
        "Uic": 4912,
    }
    value.update(overrides)
    return value


def test_explicit_short_amount_is_authoritative_even_if_opening_direction_says_buy() -> None:
    exposure = resolve_net_position_exposure_v2(
        _base(OpeningDirection="Buy"),
        net_position_id="4912_CfdOnIndex",
    )
    assert exposure is not None
    assert exposure.direction == "Sell"
    assert exposure.amount == pytest.approx(0.03)
    assert exposure.source == "AMOUNT_LONG_SHORT"


def test_real_incident_mixed_gross_book_resolves_to_net_short() -> None:
    exposure = resolve_net_position_exposure_v2(
        _base(Amount=-0.03, AmountLong=0.03, AmountShort=0.06, OpeningDirection="Buy"),
        net_position_id="4912_CfdOnIndex",
    )
    assert exposure is not None
    assert exposure.direction == "Sell"
    assert exposure.amount == pytest.approx(0.03)


def test_explicit_long_amount_is_authoritative() -> None:
    exposure = resolve_net_position_exposure_v2(
        _base(AmountLong=0.04, AmountShort=0.0, Amount=0.04, OpeningDirection="Buy"),
        net_position_id="4912_CfdOnIndex",
    )
    assert exposure is not None
    assert exposure.direction == "Buy"
    assert exposure.amount == pytest.approx(0.04)


def test_legacy_payload_falls_back_to_opening_direction_not_amount_sign() -> None:
    base = _base(Amount=0.02, OpeningDirection="Sell")
    base.pop("AmountLong")
    base.pop("AmountShort")
    exposure = resolve_net_position_exposure_v2(base, net_position_id="legacy")
    assert exposure is not None
    assert exposure.direction == "Sell"
    assert exposure.amount == pytest.approx(0.02)
    assert exposure.source == "OPENING_DIRECTION_FALLBACK"


def test_equal_intraday_gross_legs_with_zero_signed_amount_are_net_flat() -> None:
    exposure = resolve_net_position_exposure_v2(
        _base(Amount=0.0, AmountLong=0.06, AmountShort=0.06, OpeningDirection="Buy"),
        net_position_id="squared-flat",
    )
    assert exposure is None


def test_equal_gross_legs_with_nonzero_signed_amount_fail_closed() -> None:
    with pytest.raises(RuntimeError, match="contradict Amount"):
        resolve_net_position_exposure_v2(
            _base(Amount=-0.03, AmountLong=0.06, AmountShort=0.06),
            net_position_id="contradictory-squared",
        )


def test_signed_amount_must_match_explicit_long_short_difference() -> None:
    with pytest.raises(RuntimeError, match="signed Amount contradicts"):
        resolve_net_position_exposure_v2(
            _base(Amount=0.03, AmountLong=0.0, AmountShort=0.03),
            net_position_id="wrong-sign",
        )


def test_nonzero_legacy_amount_without_direction_authority_fails_closed() -> None:
    base = _base(Amount=0.03, OpeningDirection="")
    base.pop("AmountLong")
    base.pop("AmountShort")
    with pytest.raises(RuntimeError, match="lacks direction authority"):
        resolve_net_position_exposure_v2(base, net_position_id="unknown")


def test_position_adapter_and_close_payload_use_resolved_short_direction() -> None:
    class Client:
        def _get(self, path, params=None):
            assert path == "port/v1/netpositions/me"
            return {
                "Data": [
                    {
                        "NetPositionId": "4912_CfdOnIndex",
                        "NetPositionBase": _base(
                            Amount=-0.03,
                            AmountLong=0.03,
                            AmountShort=0.06,
                            OpeningDirection="Buy",
                        ),
                        "NetPositionView": {
                            "AverageOpenPriceIncludingCosts": 29111.4,
                            "CalculationReliability": "Ok",
                            "CurrentPrice": 29110.4,
                            "CurrentPriceDelayMinutes": 0,
                            "Status": "Open",
                        },
                    }
                ]
            }

    observations = risk._position_observations_v2(Client())
    assert len(observations) == 1
    observation = observations[0]
    assert observation.direction == "Sell"
    assert observation.amount == pytest.approx(0.03)
    assert observation.pnl_pct > 0

    payload = _close_payload(
        account_key="account-key",
        observation=observation,
        external_reference="test-short-close",
    )
    assert payload["BuySell"] == "Buy"
    assert payload["Amount"] == pytest.approx(0.03)


def test_position_adapter_treats_balanced_intraday_gross_book_as_flat() -> None:
    class Client:
        def _get(self, path, params=None):
            return {
                "Data": [
                    {
                        "NetPositionId": "4912_CfdOnIndex",
                        "NetPositionBase": _base(
                            Amount=0.0,
                            AmountLong=0.06,
                            AmountShort=0.06,
                            OpeningDirection="Buy",
                        ),
                        "NetPositionView": {
                            "AverageOpenPrice": 29111.4,
                            "CurrentPrice": 29111.4,
                            "Status": "Open",
                        },
                    }
                ]
            }

    assert risk._position_observations_v2(Client()) == ()
