from types import SimpleNamespace

from v2_forecast_visualization import render_v2_forecast_chart, render_v2_technical_explanation


def _view(*, interpreted: bool = False):
    return SimpleNamespace(
        market="GOLD",
        as_of="2026-08-15T10:00:00+00:00",
        horizon_seconds=3600,
        direction="BULLISH",
        baseline_return=0.004,
        expected_return=0.006 if interpreted else 0.004,
        lower_return=-0.001,
        upper_return=0.011,
        confidence=0.72,
        path_shape="TREND_CONTINUATION",
        trend_state="BULLISH",
        momentum_state="BULLISH",
        volatility_state="NORMAL",
        structure_state="HH_HL",
        technical_score=0.44,
        recipe_label="TA+Interpreter v1" if interpreted else "TA-only v1",
        applied_layers=("technical-interpreter",) if interpreted else (),
        interpreter_summary="Continuation remains favored." if interpreted else None,
        interpreter_confidence=0.68 if interpreted else None,
        price_history=(
            ("2026-08-15T09:57:00+00:00", 100.0),
            ("2026-08-15T09:58:00+00:00", 100.2),
            ("2026-08-15T09:59:00+00:00", 100.1),
            ("2026-08-15T10:00:00+00:00", 100.3),
        ),
    )


def test_chart_keeps_forecast_as_primary_object_with_history_and_uncertainty():
    markup = render_v2_forecast_chart(_view())

    assert 'class="pg-v2-history"' in markup
    assert 'class="pg-v2-fan"' in markup
    assert 'class="pg-v2-path"' in markup
    assert "NÅ → PROGNOSE" in markup
    assert "TA-only v1" in markup
    assert "pg-v2-baseline-compare" not in markup


def test_interpreter_view_shows_baseline_comparison_without_replacing_forecast():
    markup = render_v2_forecast_chart(_view(interpreted=True))

    assert 'class="pg-v2-path"' in markup
    assert 'class="pg-v2-baseline-compare"' in markup
    assert "TA+Interpreter v1" in markup


def test_explanation_surfaces_core_states_and_only_cached_interpreter_summary():
    baseline = render_v2_technical_explanation(_view())
    interpreted = render_v2_technical_explanation(_view(interpreted=True))

    for label in ("Trend", "Momentum", "Struktur", "Volatilitet", "TA-score", "Confidence"):
        assert label in baseline
    assert "Banegrunnlag" in baseline
    assert "Technical Interpreter</strong>" not in baseline
    assert "Continuation remains favored." in interpreted
