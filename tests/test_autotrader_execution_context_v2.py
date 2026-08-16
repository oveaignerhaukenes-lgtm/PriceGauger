from __future__ import annotations

from datetime import datetime, timezone

import pytest

import autotrader_execution_context_v2 as execution_v2
import autotrader_manual_execution as manual
from autotrader_execution_context_v2 import AutoTraderExecutionContextV2
from instrument_registry_v2 import InstrumentSourceV2
from saxo_provider import SaxoInstrument
from trading_desk_order_preview import build_order_preview
from trading_desk_products import LeveragedProduct


def _source(*, instrument_id: int = 11, asset_type: str = "CfdOnFutures") -> InstrumentSourceV2:
    return InstrumentSourceV2(
        market_id=7,
        market_name="Gold",
        instrument_id=instrument_id,
        instrument_type="feed",
        display_name="Gold canonical feed",
        provider="saxo",
        provider_instrument_id="4242",
        asset_type=asset_type,
        symbol="GOLD",
    )


def _context() -> AutoTraderExecutionContextV2:
    return AutoTraderExecutionContextV2.from_source(
        market_id=7,
        market_name="Gold",
        source=_source(),
    )


def _preview():
    return build_order_preview(
        market="Gold",
        product=LeveragedProduct(
            instrument=SaxoInstrument(
                asset="Gold",
                uic=9999,
                asset_type="MiniFuture",
                symbol="MINI GOLD L",
                description="Mini Gold Long",
            ),
            direction="Long",
        ),
        account_key="account-key",
        account_id="SIM-001",
        action="Buy",
        amount=2,
    )


def test_execution_context_re_resolves_exact_subscribed_v2_identity(monkeypatch) -> None:
    calls = []

    def resolve(**kwargs):
        calls.append(kwargs)
        return _source()

    monkeypatch.setattr(execution_v2, "resolve_instrument_source_v2", resolve)

    resolved = execution_v2.verify_execution_context_v2(_context())

    assert resolved.instrument_id == 11
    assert calls == [
        {
            "provider": "saxo",
            "provider_instrument_id": "4242",
            "require_subscription": True,
        }
    ]


def test_execution_context_fails_closed_on_stale_registry_identity(monkeypatch) -> None:
    monkeypatch.setattr(
        execution_v2,
        "resolve_instrument_source_v2",
        lambda **kwargs: _source(instrument_id=12),
    )

    with pytest.raises(ValueError, match="instrument_id"):
        execution_v2.verify_execution_context_v2(_context())


def test_tradingdesk_intent_requires_and_hashes_v2_context(monkeypatch) -> None:
    monkeypatch.setattr(manual, "verify_execution_context_v2", lambda context: _source())
    now = datetime(2026, 8, 16, 0, 30, tzinfo=timezone.utc)

    unbound = manual.build_manual_order_intent(_preview(), now=now)
    bound = manual.build_manual_order_intent(
        _preview(),
        execution_context_v2=_context(),
        now=now,
    )

    assert bound.intent_id != unbound.intent_id
    assert bound.execution_context_v2 == _context()
    manual.validate_manual_intent(
        bound,
        active_account_keys={"account-key"},
        require_v2_context=True,
        now=now,
    )

    with pytest.raises(ValueError, match="mangler eksplisitt v2 execution context"):
        manual.validate_manual_intent(
            unbound,
            active_account_keys={"account-key"},
            require_v2_context=True,
            now=now,
        )


def test_v2_binding_is_provenance_gate_not_execution_product(monkeypatch) -> None:
    monkeypatch.setattr(manual, "verify_execution_context_v2", lambda context: _source())
    intent = manual.build_manual_order_intent(
        _preview(),
        execution_context_v2=_context(),
        now=datetime(2026, 8, 16, 0, 30, tzinfo=timezone.utc),
    )

    payload = intent.order_request().payload()

    assert intent.execution_context_v2.provider_instrument_id == "4242"
    assert payload["Uic"] == 9999
    assert payload["AssetType"] == "MiniFuture"


def test_execute_revalidates_v2_context_before_any_order_post(monkeypatch) -> None:
    calls = []

    def reject(context):
        calls.append(context)
        raise ValueError("v2 execution context er stale")

    monkeypatch.setattr(manual, "verify_execution_context_v2", reject)
    intent = manual.build_manual_order_intent(_preview(), execution_context_v2=_context())

    class Trading:
        def place_order(self, *args, **kwargs):
            raise AssertionError("order POST must not be reached")

    submitted: set[str] = set()
    with pytest.raises(ValueError, match="stale"):
        manual.execute_confirmed_manual_order(
            Trading(),
            intent,
            confirmed_intent_id=intent.intent_id,
            submitted_intent_ids=submitted,
        )

    assert calls == [_context()]
    assert submitted == set()
