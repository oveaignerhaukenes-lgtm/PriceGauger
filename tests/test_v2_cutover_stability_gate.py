from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_overview_market_cards_are_v2_authoritative() -> None:
    source = _source("pages/0_Oversikt.py")

    assert "from overview_v2_cards import render_v2_overview_market_cards" in source
    assert "render_v2_overview_market_cards(" in source


def test_tradingdesk_identity_analysis_companion_and_automanager_are_v2_bound() -> None:
    page_source = _source("pages/0_TradingDesk.py")
    facade_source = _source("tradingdesk_automanage_panel_v2.py")
    simple_source = _source("tradingdesk_automanager_simple_v1.py")

    assert "load_trading_desk_contexts_v2" in page_source
    assert "render_companion_panel_v2" in page_source
    assert "render_tradingdesk_automanage_panel_v2(context)" in page_source
    assert "render_tradingdesk_automanager_simple_v1" in facade_source
    assert "TradingDeskV2Context" in simple_source
    assert "int(item.market_id) == int(context.market_id)" in simple_source
    assert "context.instrument.provider_instrument_id" in simple_source
    assert "context.instrument.asset_type" in simple_source
    assert "configured_instruments" not in page_source
    assert "render_saxo_product_panel" not in page_source


def test_realtime_worker_uses_v2_subscription_bridge_for_runtime_set() -> None:
    source = _source("realtime_worker.py")

    assert "load_runtime_instruments_v2" in source
    assert "instrument_signature_v2" in source
    assert "runtime_instruments = _initial_runtime_instruments(configured)" in source
    assert "instruments=runtime_instruments" in source
    assert "instruments=dict(runtime_instruments)" in source
    assert "restart_requested" in source


def test_manual_execution_revalidates_bound_v2_identity() -> None:
    source = _source("autotrader_manual_execution.py")

    assert "execution_context_v2" in source
    assert "execution_context_v2.fingerprint" in source
    assert "verify_execution_context_v2(intent.execution_context_v2)" in source
    assert "confirmed_intent_id != intent.intent_id" in source
    assert "intent.order_request()" in source


def test_v2_execution_context_is_provenance_not_product_substitution() -> None:
    source = _source("autotrader_execution_context_v2.py")

    assert "resolve_instrument_source_v2" in source
    assert "require_subscription=True" in source
    assert 'context.provider != "saxo"' in source
    assert "provider_instrument_id" in source
    # The v2 context has no order-product UIC field: concrete Saxo execution
    # identity remains owned by the separately selected manual order instrument.
    assert "execution_uic" not in source
