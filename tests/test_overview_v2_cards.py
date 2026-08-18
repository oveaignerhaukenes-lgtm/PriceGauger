from __future__ import annotations

from overview_v2_cards import (
    OverviewV2Health,
    _preferred_horizon,
    render_overview_v2_market_card_html,
)
from overview_v2_read_model import OverviewTechnicalV2


def _view(**changes) -> OverviewTechnicalV2:
    values = dict(
        market="Gold",
        as_of="2026-08-16T00:00:00+00:00",
        horizon_seconds=3600,
        available_horizons=(300, 900, 1800, 3600, 14400),
        direction="BULLISH",
        baseline_return=0.004,
        expected_return=0.006,
        lower_return=-0.002,
        upper_return=0.012,
        confidence=0.72,
        path_shape="DRIFT",
        trend_state="BULLISH",
        momentum_state="BULLISH",
        volatility_state="NORMAL",
        structure_state="HH_HL",
        technical_score=0.41,
        recipe_label="TA-only v1",
        applied_layers=(),
        interpreter_available=False,
        interpreter_summary=None,
        interpreter_confidence=None,
        price_history=(
            ("2026-08-15T23:59:00+00:00", 4400.0),
            ("2026-08-16T00:00:00+00:00", 4410.0),
        ),
    )
    values.update(changes)
    return OverviewTechnicalV2(**values)


def test_overview_v2_card_uses_v2_forecast_and_technical_explanation():
    html = render_overview_v2_market_card_html(
        _view(),
        health=OverviewV2Health("HEALTHY", "latest observation age=42s"),
        color="#123456",
        detail_href="/market?market=Gold",
    )

    assert "TEKNISK PROGNOSE" in html
    assert "LONG-BIAS" in html
    assert "TA-only v1" in html
    assert "Trend" in html
    assert "Momentum" in html
    assert "Volatilitet" in html
    assert "PROGNOSE VS. VIRKELIGHET" in html
    assert "+0.600%" in html
    assert "-0.200% til +1.200%" in html
    assert "4401.18 til 4462.92" in html
    assert "latest observation age=42s" in html


def test_overview_v2_card_marks_interpreter_as_refinement_not_baseline_replacement():
    html = render_overview_v2_market_card_html(
        _view(
            recipe_label="TA+Interpreter v1",
            applied_layers=("technical-interpreter",),
            interpreter_available=True,
            interpreter_summary="Momentum supports continuation.",
            interpreter_confidence=0.78,
        ),
        health=OverviewV2Health("STALE", "latest observation age=250s"),
        color="#123456",
        detail_href="/market?market=Gold",
    )

    assert "Technicals + Technical Interpreter" in html
    assert "Momentum supports continuation." in html
    assert "TA-only baseline" in html
    assert "STALE" in html


def test_overview_v2_defaults_to_four_hours_when_available():
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
