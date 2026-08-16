from __future__ import annotations

from context_snapshot_v2 import FRESH, ContextTargetStateV2, build_context_snapshot_v2
from parallel_forecast_evaluation_store_v2 import ParallelForecastEvaluationStoreV2
from parallel_forecast_evaluation_v2 import (
    TECH_CONTEXT,
    TECH_ONLY,
    build_parallel_forecast_experiment_v2,
)
from technical_core_v2 import TechnicalBaselineForecast, TechnicalCoreState


def _technical() -> TechnicalBaselineForecast:
    state = TechnicalCoreState(
        market="Silver",
        as_of="2026-08-17T10:00:00+00:00",
        recipe_version="technical-core-v2.1",
        primary_timeframe="30m",
        trend_state="BULLISH",
        momentum_state="BULLISH",
        volatility_state="NORMAL",
        structure_state="HH_HL",
        score=0.4,
        confidence=0.72,
        snapshots={"30m": {"rsi_14": 62.0}},
    )
    return TechnicalBaselineForecast(
        market=state.market,
        as_of=state.as_of,
        horizon_seconds=3600,
        recipe_version=state.recipe_version,
        direction="BULLISH",
        expected_return=0.004,
        lower_return=-0.002,
        upper_return=0.010,
        confidence=state.confidence,
        path_shape="DRIFT",
        technical_state=state,
    )


def _context(*, bias: float = 0.8):
    return build_context_snapshot_v2(
        as_of="2026-08-17T10:01:00+00:00",
        engine_version="context-test-v2",
        scope_key="global",
        freshness_status=FRESH,
        evidence=(),
        targets=(
            ContextTargetStateV2(
                target_key="Silver",
                directional_bias=bias,
                confidence=0.75,
                novelty=0.8,
                event_risk=0.6,
            ),
        ),
    )


def test_pair_shares_one_outcome_target_and_preserves_control_group():
    technical = _technical()
    experiment = build_parallel_forecast_experiment_v2(
        technical=technical,
        context=_context(),
    )

    assert experiment.technical.candidate_kind == TECH_ONLY
    assert experiment.technical_context.candidate_kind == TECH_CONTEXT
    assert experiment.technical.predicted_return == technical.expected_return
    assert experiment.technical.lower_return == technical.lower_return
    assert experiment.technical.upper_return == technical.upper_return
    assert experiment.technical_context.predicted_return > technical.expected_return
    assert experiment.outcome_key


def test_context_change_changes_treatment_not_outcome_target():
    technical = _technical()
    bullish = build_parallel_forecast_experiment_v2(technical=technical, context=_context(bias=0.8))
    bearish = build_parallel_forecast_experiment_v2(technical=technical, context=_context(bias=-0.8))

    assert bullish.outcome_key == bearish.outcome_key
    assert bullish.technical == bearish.technical
    assert bullish.technical_context.predicted_return != bearish.technical_context.predicted_return
    assert bullish.experiment_id != bearish.experiment_id


def test_same_inputs_produce_same_experiment_identity():
    first = build_parallel_forecast_experiment_v2(technical=_technical(), context=_context())
    second = build_parallel_forecast_experiment_v2(technical=_technical(), context=_context())

    assert first == second
    assert first.experiment_id == second.experiment_id


def test_store_is_idempotent_and_groups_by_outcome(tmp_path):
    store = ParallelForecastEvaluationStoreV2(tmp_path / "evaluation.db")
    experiment = build_parallel_forecast_experiment_v2(technical=_technical(), context=_context())

    assert store.save(experiment) is True
    assert store.save(experiment) is False
    assert store.count_for_outcome(experiment.outcome_key) == 1
