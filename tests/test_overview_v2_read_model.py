from __future__ import annotations

from types import SimpleNamespace

from overview_v2_read_model import project_workspace_v2


def _workspace():
    state = SimpleNamespace(
        trend_state="BULLISH",
        momentum_state="BULLISH",
        volatility_state="NORMAL",
        structure_state="HH_HL",
        score=0.42,
    )
    baselines = {
        300: SimpleNamespace(
            direction="BULLISH",
            expected_return=0.002,
            lower_return=-0.001,
            upper_return=0.005,
            confidence=0.64,
            path_shape="DRIFT",
        ),
        1800: SimpleNamespace(
            direction="BULLISH",
            expected_return=0.008,
            lower_return=0.001,
            upper_return=0.014,
            confidence=0.72,
            path_shape="TREND_CONTINUATION",
        ),
    }
    layer = SimpleNamespace(
        input_fingerprint="fp",
        directional_bias=0.6,
        velocity_modifier=0.4,
        uncertainty_modifier=-0.1,
        details={"human_summary": "Momentum supports continuation, with resistance still relevant."},
        confidence=0.61,
    )
    return SimpleNamespace(
        market="GOLD",
        as_of="2026-08-15T00:00:00+00:00",
        technical_state=state,
        technical_baselines=baselines,
        layer_outputs={"technical-interpreter": layer},
        fingerprint="fp",
    )


def test_projection_selects_nearest_requested_horizon_and_keeps_baseline_values():
    view = project_workspace_v2(_workspace(), requested_horizon_seconds=1500)

    assert view.market == "GOLD"
    assert view.horizon_seconds == 1800
    assert view.available_horizons == (300, 1800)
    assert view.direction == "BULLISH"
    assert view.baseline_return == 0.008
    assert view.expected_return == 0.008
    assert view.lower_return == 0.001
    assert view.upper_return == 0.014
    assert view.confidence == 0.72
    assert view.trend_state == "BULLISH"
    assert view.volatility_state == "NORMAL"
    assert view.technical_score == 0.42
    assert view.recipe_label == "TA-only v1"
    assert view.applied_layers == ()
    assert view.interpreter_available is True
    assert view.interpreter_confidence == 0.61
    assert "Momentum" in view.interpreter_summary
    assert view.path_profile[0] == (0.0, 0.0)
    assert view.path_profile[-1] == (1.0, view.expected_return)
    assert "trendfortsettelse" in view.path_rationale.lower()


def test_cached_interpreter_refines_same_baseline_without_reanalysis():
    view = project_workspace_v2(
        _workspace(),
        requested_horizon_seconds=1800,
        enable_interpreter=True,
    )

    assert view.recipe_label == "TA+Interpreter v1"
    assert view.applied_layers == ("technical-interpreter",)
    assert view.baseline_return == 0.008
    assert view.expected_return != view.baseline_return
    assert view.lower_return < view.expected_return < view.upper_return
    assert view.path_profile[-1] == (1.0, view.expected_return)


def test_projection_is_valid_without_interpreter_layer():
    workspace = _workspace()
    workspace.layer_outputs.clear()

    view = project_workspace_v2(workspace, requested_horizon_seconds=300, enable_interpreter=True)

    assert view.horizon_seconds == 300
    assert view.recipe_label == "TA-only v1"
    assert view.interpreter_available is False
    assert view.interpreter_summary is None
    assert view.interpreter_confidence is None


def test_bullish_terminal_with_bearish_momentum_gets_explicit_initial_dip():
    workspace = _workspace()
    workspace.technical_state.momentum_state = "BEARISH"

    view = project_workspace_v2(workspace, requested_horizon_seconds=1800)

    assert view.expected_return > 0
    assert view.path_profile[1][1] < 0
    assert view.path_profile[-1] == (1.0, view.expected_return)
    assert "motbevegelse" in view.path_rationale.lower()


def test_bearish_terminal_with_bullish_momentum_mirrors_counter_move_upward():
    workspace = _workspace()
    workspace.technical_state.trend_state = "BEARISH"
    workspace.technical_state.momentum_state = "BULLISH"
    workspace.technical_state.structure_state = "LH_LL"
    workspace.technical_baselines[1800] = SimpleNamespace(
        direction="BEARISH",
        expected_return=-0.008,
        lower_return=-0.014,
        upper_return=-0.001,
        confidence=0.72,
        path_shape="TREND_CONTINUATION",
    )

    view = project_workspace_v2(workspace, requested_horizon_seconds=1800)

    assert view.expected_return < 0
    assert view.path_profile[1][1] > 0
    assert view.path_profile[-1] == (1.0, view.expected_return)
