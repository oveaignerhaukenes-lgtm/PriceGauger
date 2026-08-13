from __future__ import annotations

from dataclasses import replace

from technical_core_v2 import TechnicalBaselineForecast, TechnicalCoreState
from technical_interpreter_v2 import TechnicalInterpretation
from workspace_composer_v2 import (
    AnalysisRecipe,
    ForecastLayerOutput,
    WorkspaceSnapshot,
    apply_technical_interpretation,
    compose_forecast,
)


def _state(*, score: float = 0.35, confidence: float = 0.7) -> TechnicalCoreState:
    return TechnicalCoreState(
        market="Silver",
        as_of="2026-08-14T00:00:00+00:00",
        recipe_version="technical-core-v2.1",
        primary_timeframe="30m",
        trend_state="BULLISH",
        momentum_state="BULLISH",
        volatility_state="NORMAL",
        structure_state="HH_HL",
        score=score,
        confidence=confidence,
        snapshots={"30m": {"rsi_14": 62.0, "macd_histogram": 0.1}},
    )


def _baseline(state: TechnicalCoreState | None = None) -> TechnicalBaselineForecast:
    state = state or _state()
    return TechnicalBaselineForecast(
        market=state.market,
        as_of=state.as_of,
        horizon_seconds=3600,
        recipe_version=state.recipe_version,
        direction="BULLISH",
        expected_return=0.004,
        lower_return=-0.002,
        upper_return=0.01,
        confidence=state.confidence,
        path_shape="DRIFT",
        technical_state=state,
    )


def _workspace() -> WorkspaceSnapshot:
    baseline = _baseline()
    return WorkspaceSnapshot.from_baselines({baseline.horizon_seconds: baseline})


def test_technical_only_recipe_preserves_frozen_baseline():
    workspace = _workspace()
    recipe = AnalysisRecipe(name="ta-only", version=1, enabled_layers=())

    composed = compose_forecast(workspace, horizon_seconds=3600, recipe=recipe)

    assert composed.baseline_return == 0.004
    assert composed.composed_return == 0.004
    assert composed.lower_return == -0.002
    assert composed.upper_return == 0.01
    assert composed.applied_layers == ()


def test_technical_interpreter_can_refine_without_mutating_baseline():
    workspace = _workspace()
    interpretation = TechnicalInterpretation(
        market="Silver",
        as_of="2026-08-14T00:00:00+00:00",
        recipe_version="technical-interpreter-v2.1",
        directional_bias="BULLISH",
        continuation_probability=0.76,
        mean_reversion_probability=0.24,
        breakout_probability=0.7,
        rejection_probability=0.3,
        squeeze_probability=0.15,
        confidence=0.78,
        emphasis={"momentum": 0.9, "volume": 0.8},
        human_summary="Momentum and participation support continuation.",
        source_technical_recipe="technical-core-v2.1",
    )
    layer = apply_technical_interpretation(workspace, interpretation)
    workspace = workspace.with_layer_output(layer)
    recipe = AnalysisRecipe(name="ta-plus-interpreter", version=1, enabled_layers=("technical_interpreter",))

    composed = compose_forecast(workspace, horizon_seconds=3600, recipe=recipe)

    assert composed.baseline_return == 0.004
    assert composed.composed_return > composed.baseline_return
    assert composed.applied_layers == ("technical_interpreter",)
    assert _baseline().expected_return == 0.004


def test_stale_layer_output_is_rejected_by_workspace_fingerprint():
    workspace = _workspace()
    stale = ForecastLayerOutput(
        layer_name="technical_interpreter",
        layer_version="technical-interpreter-v2.1",
        workspace_fingerprint="stale-fingerprint",
        directional_bias=0.4,
        velocity_modifier=1.0,
        uncertainty_modifier=1.0,
        reversal_probability=0.2,
        squeeze_probability=0.1,
        confidence=0.7,
        details={},
    )

    try:
        workspace.with_layer_output(stale)
    except ValueError as exc:
        assert "fingerprint" in str(exc).lower()
    else:
        raise AssertionError("Expected ValueError")


def test_new_technical_state_changes_workspace_fingerprint():
    first = _workspace()
    changed_state = replace(_state(), as_of="2026-08-14T00:01:00+00:00", score=0.2)
    second = WorkspaceSnapshot.from_baselines({3600: _baseline(changed_state)})

    assert first.fingerprint != second.fingerprint


def test_recipe_can_toggle_cached_layer_without_recomputing_baseline():
    workspace = _workspace()
    layer = ForecastLayerOutput(
        layer_name="technical_interpreter",
        layer_version="technical-interpreter-v2.1",
        workspace_fingerprint=workspace.fingerprint,
        directional_bias=-0.3,
        velocity_modifier=0.9,
        uncertainty_modifier=1.2,
        reversal_probability=0.65,
        squeeze_probability=0.1,
        confidence=0.7,
        details={},
    )
    workspace = workspace.with_layer_output(layer)

    ta_only = compose_forecast(workspace, horizon_seconds=3600, recipe=AnalysisRecipe(name="ta", version=1, enabled_layers=()))
    interpreted = compose_forecast(workspace, horizon_seconds=3600, recipe=AnalysisRecipe(name="ta+i", version=1, enabled_layers=("technical_interpreter",)))

    assert ta_only.baseline_return == interpreted.baseline_return == 0.004
    assert ta_only.composed_return != interpreted.composed_return
