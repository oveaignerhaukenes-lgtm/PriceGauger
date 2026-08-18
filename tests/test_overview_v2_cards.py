from __future__ import annotations

from overview_v2_cards import _preferred_horizon


def test_overview_v2_default_horizon_prefers_four_hours():
    available = (300, 900, 1800, 3600, 14400, 43200)
    assert _preferred_horizon(available, {}, "Gold") == 14400


def test_overview_v2_honors_previous_legacy_horizon_selection():
    available = (300, 900, 1800, 3600, 14400)
    session_state = {"overview_forecast_horizon:Gold": 1.0}
    assert _preferred_horizon(available, session_state, "Gold") == 3600


def test_overview_page_active_market_fragment_is_v2_only():
    source = open("pages/0_Oversikt.py", encoding="utf-8").read()
    start = source.index("def _render_live_market_cards")
    end = source.index("\n\n_render_context_v2()", start)
    fragment_source = source[start:end]

    assert "render_v2_overview_market_cards" in fragment_source
    assert "load_overview_markets" not in fragment_source
    assert "render_forecast_timeline_svg" not in fragment_source
    assert "Decision State" not in fragment_source
    assert "RealtimeMarketDataStore" not in fragment_source


def test_overview_v2_card_module_has_no_analysis_or_provider_side_effect_path():
    source = open("overview_v2_cards.py", encoding="utf-8").read().lower()
    assert "technical_interpreter_runtime_v2" not in source
    assert "openai" not in source
    assert "saxo_" not in source
    assert "persist_" not in source
    assert "build_technical_core_state" not in source
    assert ".pg-market-card-v2 .pg-v2-path{stroke:var(--market-color)}" in source
