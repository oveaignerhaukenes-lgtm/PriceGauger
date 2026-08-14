from __future__ import annotations

from technical_core_v2 import TechnicalBaselineForecast, TechnicalCoreState
from technical_interpreter_runtime_v2 import run_technical_interpreter_v2
from workspace_composer_v2 import AnalysisRecipeV2, WorkspaceSnapshotV2, compose_forecast


def _workspace() -> WorkspaceSnapshotV2:
    state = TechnicalCoreState(
        market="Silver",
        as_of="2026-08-14T00:00:00+00:00",
        recipe_version="technical-core-v2.1",
        primary_timeframe="30m",
        trend_state="BULLISH",
        momentum_state="BULLISH",
        volatility_state="NORMAL",
        structure_state="HH_HL",
        score=0.35,
        confidence=0.7,
        snapshots={"30m": {"rsi_14": 62.0, "macd_histogram": 0.1}},
    )
    baseline = TechnicalBaselineForecast(
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
    return WorkspaceSnapshotV2(
        market=state.market,
        as_of=state.as_of,
        technical_state=state,
        technical_baselines={3600: baseline},
    )


def _valid_response() -> dict:
    return {
        "directional_bias": "BULLISH",
        "continuation_probability": 0.76,
        "mean_reversion_probability": 0.24,
        "breakout_probability": 0.70,
        "rejection_probability": 0.30,
        "squeeze_probability": 0.15,
        "confidence": 0.78,
        "emphasis": {"momentum": 0.9, "structure": 0.8},
        "human_summary": "Momentum and structure support continuation.",
    }


def test_runtime_callable_receives_only_technical_payload_and_caches_output():
    workspace = _workspace()
    received = []

    def fake_interpreter(payload):
        received.append(payload)
        return _valid_response()

    result = run_technical_interpreter_v2(
        workspace=workspace,
        interpreter=fake_interpreter,
    )

    assert result.source == "generated"
    assert result.output.layer_name == "technical-interpreter"
    assert workspace.layer_outputs["technical-interpreter"] == result.output
    assert len(received) == 1
    assert set(received[0]) == {
        "market",
        "as_of",
        "technical_recipe",
        "primary_timeframe",
        "trend_state",
        "momentum_state",
        "volatility_state",
        "structure_state",
        "baseline_score",
        "baseline_confidence",
        "snapshots",
    }
    assert "news" not in received[0]
    assert "position" not in received[0]
    assert "macro" not in received[0]


def test_matching_cache_prevents_second_interpreter_call():
    workspace = _workspace()
    calls = 0

    def fake_interpreter(payload):
        nonlocal calls
        calls += 1
        return _valid_response()

    first = run_technical_interpreter_v2(workspace=workspace, interpreter=fake_interpreter)
    second = run_technical_interpreter_v2(workspace=workspace, interpreter=fake_interpreter)

    assert first.source == "generated"
    assert second.source == "cache"
    assert second.output == first.output
    assert calls == 1


def test_invalid_structured_output_cannot_enter_workspace():
    workspace = _workspace()
    invalid = _valid_response()
    invalid["breakout_probability"] = 1.4

    def fake_interpreter(payload):
        return invalid

    try:
        run_technical_interpreter_v2(workspace=workspace, interpreter=fake_interpreter)
    except ValueError as exc:
        assert "breakout_probability" in str(exc)
    else:
        raise AssertionError("Expected ValueError")

    assert "technical-interpreter" not in workspace.layer_outputs


def test_technical_only_forecast_remains_identical_after_interpreter_generation():
    workspace = _workspace()
    before = compose_forecast(
        workspace,
        horizon_seconds=3600,
        recipe=AnalysisRecipeV2(name="ta", version=1, enabled_layers=()),
    )

    run_technical_interpreter_v2(
        workspace=workspace,
        interpreter=lambda payload: _valid_response(),
    )

    after = compose_forecast(
        workspace,
        horizon_seconds=3600,
        recipe=AnalysisRecipeV2(name="ta", version=1, enabled_layers=()),
    )
    interpreted = compose_forecast(
        workspace,
        horizon_seconds=3600,
        recipe=AnalysisRecipeV2(
            name="ta+i",
            version=1,
            enabled_layers=("technical-interpreter",),
        ),
    )

    assert after.composed_return == before.composed_return == 0.004
    assert after.lower_return == before.lower_return == -0.002
    assert after.upper_return == before.upper_return == 0.01
    assert interpreted.baseline_return == 0.004
    assert interpreted.composed_return != 0.004


def test_persistence_requires_market_id_before_interpreter_or_workspace_mutation():
    workspace = _workspace()
    calls = 0

    def fake_interpreter(payload):
        nonlocal calls
        calls += 1
        return _valid_response()

    try:
        run_technical_interpreter_v2(
            workspace=workspace,
            interpreter=fake_interpreter,
            persist=True,
        )
    except ValueError as exc:
        assert "market_id" in str(exc)
    else:
        raise AssertionError("Expected ValueError")

    assert calls == 0
    assert "technical-interpreter" not in workspace.layer_outputs
