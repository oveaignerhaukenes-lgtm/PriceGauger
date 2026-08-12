from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from autotrader_manual_execution import (
    build_manual_order_intent,
    execute_confirmed_manual_order,
    precheck_is_clear,
    validate_manual_intent,
)
from saxo_provider import SaxoInstrument
from saxo_trading import SaxoTradingSafetyError
from trading_desk_order_preview import build_order_preview
from trading_desk_products import LeveragedProduct


def _preview():
    product = LeveragedProduct(
        instrument=SaxoInstrument(
            asset="Gold",
            uic=12345,
            asset_type="MiniFuture",
            symbol="MINI GOLD L",
            description="Mini Future Long Gold",
        ),
        direction="Long",
    )
    return build_order_preview(
        market="Gold",
        product=product,
        account_key="account-key",
        account_id="SIM-001",
        action="Buy",
        amount=2,
    )


def test_manual_intent_builds_manual_order_with_external_reference() -> None:
    intent = build_manual_order_intent(
        _preview(),
        now=datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc),
    )
    payload = intent.order_request().payload()

    assert intent.intent_id.startswith("pg-")
    assert payload["ManualOrder"] is True
    assert payload["BuySell"] == "Buy"
    assert payload["Amount"] == 2.0
    assert payload["Uic"] == 12345
    assert payload["ExternalReference"] == intent.intent_id


def test_manual_intent_must_be_fresh_and_use_active_account() -> None:
    created = datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc)
    intent = build_manual_order_intent(_preview(), now=created)

    validate_manual_intent(intent, active_account_keys={"account-key"}, now=created + timedelta(minutes=4))

    with pytest.raises(ValueError, match="stale"):
        validate_manual_intent(intent, active_account_keys={"account-key"}, now=created + timedelta(minutes=6))
    with pytest.raises(ValueError, match="aktiv Saxo SIM-konto"):
        validate_manual_intent(intent, active_account_keys={"other"}, now=created)


def test_precheck_requires_ok_and_no_disclaimers() -> None:
    assert precheck_is_clear({"PreCheckResult": "Ok"}) is True
    assert precheck_is_clear({"PreCheckResult": "Error"}) is False
    assert precheck_is_clear({"PreCheckResult": "Ok", "PreTradeDisclaimers": [{"id": 1}]}) is False


class _Trading:
    def __init__(self) -> None:
        self.place_calls = 0

    def place_order(self, order, *, confirm_sim=False):
        assert confirm_sim is True
        self.place_calls += 1
        return {"OrderId": "42"}

    def open_orders_me(self, *, account_key, uic):
        assert account_key == "account-key"
        assert uic == 12345
        return ({"OrderId": "42", "Uic": uic},)

    def net_positions_me(self, *, account_id, uic):
        assert account_id == "SIM-001"
        assert uic == 12345
        return ({"NetPositionBase": {"PositionsAccount": account_id, "Uic": uic, "Amount": 2}},)


def test_confirmed_manual_order_places_once_and_reconciles() -> None:
    trading = _Trading()
    intent = build_manual_order_intent(_preview())
    submitted: set[str] = set()

    result = execute_confirmed_manual_order(
        trading,
        intent,
        confirmed_intent_id=intent.intent_id,
        submitted_intent_ids=submitted,
    )

    assert result.order_id == "42"
    assert len(result.open_orders) == 1
    assert len(result.net_positions) == 1
    assert trading.place_calls == 1
    assert intent.intent_id in submitted

    with pytest.raises(SaxoTradingSafetyError, match="allerede forsøkt"):
        execute_confirmed_manual_order(
            trading,
            intent,
            confirmed_intent_id=intent.intent_id,
            submitted_intent_ids=submitted,
        )
    assert trading.place_calls == 1


def test_confirmation_must_match_exact_intent() -> None:
    trading = _Trading()
    intent = build_manual_order_intent(_preview())

    with pytest.raises(SaxoTradingSafetyError, match="gjeldende ordreintent"):
        execute_confirmed_manual_order(
            trading,
            intent,
            confirmed_intent_id="wrong",
            submitted_intent_ids=set(),
        )
    assert trading.place_calls == 0
