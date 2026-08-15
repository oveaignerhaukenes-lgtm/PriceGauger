from __future__ import annotations

from recipe_registry_v2 import TA_ONLY_V1
from technical_core_v2 import build_baseline_forecast, build_technical_core_state
from timeframe_contract_v2 import build_runtime_frames_from_canonical_1m_v2
from workspace_composer_v2 import AnalysisRecipeV2, WorkspaceSnapshotV2, compose_forecast


def _rising_points(count: int = 240) -> list[tuple[str, float]]:
    base = 100.0
    return [
        (f"2026-08-14T{10 + minute // 60:02d}:{minute % 60:02d}:00Z", base + minute * 0.05)
        for minute in range(count)
    ]


def test_canonical_1m_to_ta_only_forecast_is_deterministic_end_to_end():
    points = _rising_points()

    frames_a = build_runtime_frames_from_canonical_1m_v2(points)
    frames_b = build_runtime_frames_from_canonical_1m_v2(points)
    state_a = build_technical_core_state(frames_a, market="TEST")
    state_b = build_technical_core_state(frames_b, market="TEST")

    assert state_a == state_b
    assert state_a.primary_timeframe == "30m"
    assert state_a.as_of == state_b.as_of

    baseline_a = build_baseline_forecast(state_a, horizon_seconds=1800)
    baseline_b = build_baseline_forecast(state_b, horizon_seconds=1800)
    assert baseline_a == baseline_b

    workspace = WorkspaceSnapshotV2(
        market="TEST",
        as_of=state_a.as_of,
        technical_state=state_a,
        technical_baselines={1800: baseline_a},
    )
    recipe = AnalysisRecipeV2(
        name=TA_ONLY_V1.name,
        version=TA_ONLY_V1.version,
        enabled_layers=TA_ONLY_V1.enabled_layers,
    )
    composed = compose_forecast(workspace, horizon_seconds=1800, recipe=recipe)

    assert composed.applied_layers == ()
    assert composed.baseline_return == baseline_a.expected_return
    assert composed.composed_return == baseline_a.expected_return
    assert composed.lower_return == baseline_a.lower_return
    assert composed.upper_return == baseline_a.upper_return


def test_missing_minutes_do_not_create_synthetic_observations_in_stability_path():
    points = _rising_points(120)
    points = [point for index, point in enumerate(points) if index not in {17, 18, 61, 62, 63}]

    frames = build_runtime_frames_from_canonical_1m_v2(points)

    assert len(frames["1m"]) == 115
    assert not frames["30m"].empty
    state = build_technical_core_state(frames, market="TEST")
    baseline = build_baseline_forecast(state, horizon_seconds=1800)
    assert baseline.market == "TEST"
    assert baseline.as_of == state.as_of
