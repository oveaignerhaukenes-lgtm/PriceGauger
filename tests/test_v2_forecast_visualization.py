import re
from types import SimpleNamespace

from v2_forecast_visualization import _path_return, render_v2_forecast_chart, render_v2_technical_explanation


def _view(*, interpreted: bool = False, counter_move: bool = False, ghosts=(), price_history=None):
    expected = 0.006 if interpreted else 0.004
    path_profile = (
        (0.0, 0.0),
        (0.2, -0.0012),
        (0.45, 0.0004),
        (0.7, expected * 0.55),
        (1.0, expected),
    ) if counter_move else (
        (0.0, 0.0),
        (0.2, expected * 0.22),
        (0.46, expected * 0.52),
        (0.73, expected * 0.79),
        (1.0, expected),
    )
    return SimpleNamespace(
        market="GOLD",
        as_of="2026-08-15T10:00:00+00:00",
        horizon_seconds=3600,
        direction="BULLISH",
        baseline_return=0.004,
        expected_return=expected,
        lower_return=-0.001,
        upper_return=0.011,
        confidence=0.72,
        path_shape="TREND_CONTINUATION",
        trend_state="BULLISH",
        momentum_state="BEARISH" if counter_move else "BULLISH",
        volatility_state="NORMAL",
        structure_state="HH_HL",
        technical_score=0.44,
        recipe_label="TA+Interpreter v1" if interpreted else "TA-only v1",
        applied_layers=("technical-interpreter",) if interpreted else (),
        interpreter_summary="Continuation remains favored." if interpreted else None,
        interpreter_confidence=0.68 if interpreted else None,
        path_profile=path_profile,
        path_rationale=(
            "Momentum går mot terminalretningen: kort motbevegelse forventes før hovedretningen eventuelt tar over."
            if counter_move
            else "Trend, momentum og struktur støtter terminalretningen: relativt jevn trendfortsettelse."
        ),
        feed_delay_minutes=10.0,
        forecast_ghosts=tuple(ghosts),
        price_history=price_history or (
            ("2026-08-15T08:00:00+00:00", 99.4),
            ("2026-08-15T08:30:00+00:00", 99.8),
            ("2026-08-15T09:00:00+00:00", 100.0),
            ("2026-08-15T09:30:00+00:00", 100.2),
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
    assert "delay 10m" in markup
    assert "pg-v2-baseline-compare" not in markup


def test_historical_forecasts_render_as_faded_paths_with_their_uncertainty():
    ghost = SimpleNamespace(
        as_of="2026-08-15T08:30:00+00:00",
        horizon_seconds=3600,
        expected_return=0.003,
        lower_return=-0.002,
        upper_return=0.008,
        path_shape="TREND_CONTINUATION",
        path_profile=(),
    )
    markup = render_v2_forecast_chart(_view(ghosts=(ghost,)))
    assert 'class="pg-v2-ghost-path"' in markup
    assert 'class="pg-v2-ghost-fan"' in markup
    assert "1 ghosts" in markup
    assert "stroke-opacity:" in markup
    assert "fill-opacity:" in markup


def test_long_context_history_is_zoomed_to_recent_ghost_window():
    history = tuple(
        (f"2026-08-{day:02d}T10:00:00+00:00", 95.0 + day * 0.2)
        for day in range(1, 16)
    )
    ghost = SimpleNamespace(
        as_of="2026-08-15T09:00:00+00:00",
        horizon_seconds=3600,
        expected_return=0.003,
        lower_return=-0.002,
        upper_return=0.008,
        path_shape="TREND_CONTINUATION",
        path_profile=(),
    )
    markup = render_v2_forecast_chart(_view(ghosts=(ghost,), price_history=history))
    match = re.search(r'class="pg-v2-ghost-path"[^>]*points="([0-9.]+),', markup)
    assert match is not None
    assert float(match.group(1)) < 55.0


def test_interpreter_view_shows_baseline_comparison_without_replacing_forecast():
    markup = render_v2_forecast_chart(_view(interpreted=True))
    assert 'class="pg-v2-path"' in markup
    assert 'class="pg-v2-baseline-compare"' in markup
    assert "TA+Interpreter v1" in markup


def test_renderer_consumes_non_monotone_path_profile_instead_of_inventing_monotone_curve():
    view = _view(counter_move=True)
    assert _path_return(view, 0.2) < 0
    assert _path_return(view, 0.45) > 0
    assert _path_return(view, 1.0) == view.expected_return
    markup = render_v2_forecast_chart(view)
    assert 'class="pg-v2-path"' in markup


def test_explanation_surfaces_core_states_and_explicit_path_rationale():
    baseline = render_v2_technical_explanation(_view(counter_move=True))
    interpreted = render_v2_technical_explanation(_view(interpreted=True))
    for label in ("Trend", "Momentum", "Struktur", "Volatilitet", "TA-score", "Confidence"):
        assert label in baseline
    assert "Banegrunnlag" in baseline
    assert "motbevegelse" in baseline
    assert "Technical Interpreter</strong>" not in baseline
    assert "Continuation remains favored." in interpreted
