from __future__ import annotations

import inspect

import pytest

import manual_mix_preview_v2
from manual_mix_preview_v2 import blend_manual_mix_preview_v2
from parallel_forecast_evaluation_v2 import ForecastCandidateV2, ParallelForecastExperimentV2


def _experiment() -> ParallelForecastExperimentV2:
    return ParallelForecastExperimentV2(
        experiment_id="exp-1",
        outcome_key="out-1",
        market="GOLD",
        forecast_as_of="2026-08-17T10:00:00+00:00",
        horizon_seconds=3600,
        evaluation_version="parallel-evaluation-v2.0",
        technical=ForecastCandidateV2(
            candidate_kind="TECH_ONLY",
            predicted_return=0.01,
            lower_return=0.0,
            upper_return=0.02,
            direction="BULLISH",
            recipe_version="technical-core-v2.1",
            source_fingerprint="ta",
        ),
        technical_context=ForecastCandidateV2(
            candidate_kind="TECH_CONTEXT",
            predicted_return=0.03,
            lower_return=0.01,
            upper_return=0.05,
            direction="BULLISH",
            recipe_version="holistic-composer-v1.0",
            source_fingerprint="ctx",
        ),
        context_snapshot_id="ctx-1",
        context_fingerprint="ctx-fp",
    )


def test_manual_mix_endpoints_and_midpoint_are_linear():
    experiment = _experiment()
    technical = blend_manual_mix_preview_v2(experiment, mix_fraction=0.0)
    midpoint = blend_manual_mix_preview_v2(experiment, mix_fraction=0.5)
    context = blend_manual_mix_preview_v2(experiment, mix_fraction=1.0)

    assert technical.preview_return == pytest.approx(0.01)
    assert context.preview_return == pytest.approx(0.03)
    assert midpoint.preview_return == pytest.approx(0.02)
    assert midpoint.preview_lower_return == pytest.approx(0.005)
    assert midpoint.preview_upper_return == pytest.approx(0.035)
    assert midpoint.experiment_id == experiment.experiment_id
    assert midpoint.outcome_key == experiment.outcome_key


def test_manual_mix_rejects_out_of_range_weights():
    with pytest.raises(ValueError):
        blend_manual_mix_preview_v2(_experiment(), mix_fraction=-0.01)
    with pytest.raises(ValueError):
        blend_manual_mix_preview_v2(_experiment(), mix_fraction=1.01)


def test_preview_module_has_no_learning_or_write_authority():
    source = inspect.getsource(manual_mix_preview_v2)
    forbidden = (
        "INSERT INTO",
        "UPDATE ",
        "DELETE FROM",
        "save(",
        "learning_enabled",
        "train",
        "fit(",
        "AutoTrader",
        "place_order",
    )
    for token in forbidden:
        assert token not in source
