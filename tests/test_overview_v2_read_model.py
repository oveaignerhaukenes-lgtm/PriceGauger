from __future__ import annotations

from types import SimpleNamespace

from overview_v2_read_model import project_workspace_v2


def _workspace():
    state = SimpleNamespace(
        trend_state="UP",
        momentum_state="POSITIVE",
        structure_state="HH_HL",
    )
    baselines = {
        300: SimpleNamespace(
            direction="BULLISH",
            expected_return=0.002,
            lower_return=-0.001,
            upper_return=0.005,
            confidence=0.64,
            path_shape="TREND",
        ),
        1800: SimpleNamespace(
            direction="BULLISH",
            expected_return=0.008,
            lower_return=0.001,
            upper_return=0.014,
            confidence=0.72,
            path_shape="TREND",
        ),
    }
    layer = SimpleNamespace(
        details={"human_summary": "Momentum supports continuation, with resistance still relevant."},
        confidence=0.61,
    )
    return SimpleNamespace(
        market="GOLD",
        as_of="2026-08-15T00:00:00+00:00",
        technical_state=state,
        technical_baselines=baselines,
        layer_outputs={"technical-interpreter": layer},
    )


def test_projection_selects_nearest_requested_horizon_and_keeps_baseline_values():
    view = project_workspace_v2(_workspace(), requested_horizon_seconds=1500)

    assert view.market == "GOLD"
    assert view.horizon_seconds == 1800
    assert view.direction == "BULLISH"
    assert view.expected_return == 0.008
    assert view.lower_return == 0.001
    assert view.upper_return == 0.014
    assert view.confidence == 0.72
    assert view.trend_state == "UP"
    assert view.interpreter_confidence == 0.61
    assert "Momentum" in view.interpreter_summary


def test_projection_is_valid_without_interpreter_layer():
    workspace = _workspace()
    workspace.layer_outputs.clear()

    view = project_workspace_v2(workspace, requested_horizon_seconds=300)

    assert view.horizon_seconds == 300
    assert view.interpreter_summary is None
    assert view.interpreter_confidence is None
