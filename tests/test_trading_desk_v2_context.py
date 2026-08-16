from __future__ import annotations

from instrument_registry_v2 import InstrumentSourceV2
from overview_v2_read_model import OverviewTechnicalV2
from runtime_health_v2 import RuntimeHealthV2
import trading_desk_v2_context as module


def _view(market: str = "Gold") -> OverviewTechnicalV2:
    return OverviewTechnicalV2(
        market=market,
        as_of="2026-08-15T22:40:00+00:00",
        horizon_seconds=3600,
        available_horizons=(300, 3600, 14400),
        direction="BULLISH",
        baseline_return=0.01,
        expected_return=0.01,
        lower_return=-0.005,
        upper_return=0.02,
        confidence=0.7,
        path_shape="continuation",
        trend_state="BULLISH",
        momentum_state="POSITIVE",
        volatility_state="NORMAL",
        structure_state="TRENDING",
        technical_score=0.6,
        recipe_label="TA-only v1",
        applied_layers=(),
        interpreter_available=False,
        interpreter_summary=None,
        interpreter_confidence=None,
        price_history=(("2026-08-15T22:39:00+00:00", 4400.0),),
    )


def _instrument(market: str = "Gold") -> InstrumentSourceV2:
    return InstrumentSourceV2(
        market_id=7,
        market_name=market,
        instrument_id=42,
        instrument_type="CfdOnFutures",
        display_name="Gold Dec 2026 [CfdOnFutures:12345]",
        provider="saxo",
        provider_instrument_id="12345",
        asset_type="CfdOnFutures",
        symbol="GOLDDEC26",
        price_multiplier=1.0,
        metadata={},
    )


def test_context_uses_v2_market_and_instrument_identity(monkeypatch) -> None:
    monkeypatch.setattr(module, "load_v2_overview_snapshots", lambda **kwargs: {"Gold": _view()})
    monkeypatch.setattr(module, "_active_market_ids", lambda: {"Gold": 7})
    monkeypatch.setattr(module, "list_subscribed_sources_v2", lambda provider=None: (_instrument(),))
    monkeypatch.setattr(
        module,
        "load_runtime_health_v2",
        lambda **kwargs: (RuntimeHealthV2("v2-technical-runtime", "Gold", "HEALTHY", "ok", 2.0),),
    )

    context = module.load_trading_desk_contexts_v2()["Gold"]

    assert context.market_id == 7
    assert context.market_name == "Gold"
    assert context.instrument_id == 42
    assert "saxo:12345" in context.instrument_label
    assert context.forecast.recipe_label == "TA-only v1"


def test_missing_instrument_is_explicitly_degraded_not_guessed(monkeypatch) -> None:
    monkeypatch.setattr(module, "load_v2_overview_snapshots", lambda **kwargs: {"Gold": _view()})
    monkeypatch.setattr(module, "_active_market_ids", lambda: {"Gold": 7})
    monkeypatch.setattr(module, "list_subscribed_sources_v2", lambda provider=None: ())
    monkeypatch.setattr(module, "load_runtime_health_v2", lambda **kwargs: ())

    context = module.load_trading_desk_contexts_v2()["Gold"]

    assert context.market_id == 7
    assert context.instrument is None
    assert context.instrument_id is None
    assert context.health.status == "DEGRADED"
    assert "ingen aktiv/subscribed v2-instrumentkilde" in context.health.detail


def test_workspace_without_active_v2_market_identity_is_not_surfaced(monkeypatch) -> None:
    monkeypatch.setattr(module, "load_v2_overview_snapshots", lambda **kwargs: {"Ghost": _view("Ghost")})
    monkeypatch.setattr(module, "_active_market_ids", lambda: {})
    monkeypatch.setattr(module, "list_subscribed_sources_v2", lambda provider=None: ())
    monkeypatch.setattr(module, "load_runtime_health_v2", lambda **kwargs: ())

    assert module.load_trading_desk_contexts_v2() == {}
