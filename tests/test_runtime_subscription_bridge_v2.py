from __future__ import annotations

from instrument_registry_v2 import InstrumentSourceV2
from runtime_subscription_bridge_v2 import instrument_signature_v2, load_runtime_instruments_v2
from saxo_provider import SaxoInstrument
import runtime_subscription_bridge_v2 as bridge


def _configured(market: str, uic: int) -> SaxoInstrument:
    return SaxoInstrument(
        asset=market,
        uic=uic,
        asset_type="ContractFutures",
        symbol=market.upper(),
        description=f"{market} configured",
        price_multiplier=1.0,
    )


def _source(market: str, instrument_id: int, uic: int) -> InstrumentSourceV2:
    return InstrumentSourceV2(
        market_id=instrument_id + 100,
        market_name=market,
        instrument_id=instrument_id,
        instrument_type="MiniFuture",
        display_name=f"{market} selected product",
        provider="saxo",
        provider_instrument_id=str(uic),
        asset_type="MiniFuture",
        symbol=f"MINI {market.upper()}",
        price_multiplier=0.01,
        metadata={"description": f"{market} selected product"},
    )


def test_enabled_registry_subscription_overrides_same_market_configured_feed(monkeypatch) -> None:
    monkeypatch.setattr(bridge, "list_subscribed_sources_v2", lambda **kwargs: (_source("Gold", 7, 9001),))

    resolved = load_runtime_instruments_v2({"Gold": _configured("Gold", 42), "Silver": _configured("Silver", 43)})

    assert resolved.registry_markets == ("Gold",)
    assert resolved.instruments["Gold"].uic == 9001
    assert resolved.instruments["Gold"].asset_type == "MiniFuture"
    assert resolved.instruments["Gold"].price_multiplier == 0.01
    assert resolved.instruments["Silver"].uic == 43


def test_multiple_enabled_instruments_for_one_market_fail_closed(monkeypatch) -> None:
    monkeypatch.setattr(
        bridge,
        "list_subscribed_sources_v2",
        lambda **kwargs: (_source("Gold", 7, 9001), _source("Gold", 8, 9002)),
    )

    try:
        load_runtime_instruments_v2({})
    except RuntimeError as exc:
        assert "exactly one enabled collection instrument" in str(exc)
        assert "Gold" in str(exc)
    else:
        raise AssertionError("ambiguous canonical market collection must fail closed")


def test_runtime_signature_changes_when_provider_identity_changes() -> None:
    first = {"Gold": _configured("Gold", 42)}
    second = {"Gold": _configured("Gold", 43)}

    assert instrument_signature_v2(first) != instrument_signature_v2(second)
