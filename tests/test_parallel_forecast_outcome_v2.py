from __future__ import annotations

import pytest

from context_snapshot_v2 import FRESH, ContextTargetStateV2, build_context_snapshot_v2
from parallel_forecast_evaluation_v2 import build_parallel_forecast_experiment_v2
from parallel_forecast_outcome_store_v2 import ParallelForecastOutcomeStoreV2
from parallel_forecast_outcome_v2 import evaluate_parallel_forecast_experiment_v2
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
        snapshots={},
    )
    return TechnicalBaselineForecast(
        market=state.market,
        as_of=state.as_of,
        horizon_seconds=300,
        recipe_version=state.recipe_version,
        direction="BULLISH",
        expected_return=0.01,
        lower_return=-0.01,
        upper_return=0.03,
        confidence=state.confidence,
        path_shape="DRIFT",
        technical_state=state,
    )


def _experiment():
    context = build_context_snapshot_v2(
        as_of="2026-08-17T10:00:30+00:00",
        engine_version="test-context",
        scope_key="global",
        freshness_status=FRESH,
        evidence=(),
        targets=(
            ContextTargetStateV2(
                target_key="Silver",
                directional_bias=0.8,
                confidence=0.75,
                novelty=0.8,
                event_risk=0.6,
            ),
        ),
    )
    return build_parallel_forecast_experiment_v2(technical=_technical(), context=context)


def _points():
    return [
        ("2026-08-17T10:00:00Z", 100.0),
        ("2026-08-17T10:01:00Z", 100.4),
        ("2026-08-17T10:02:00Z", 100.8),
        ("2026-08-17T10:03:00Z", 101.2),
        ("2026-08-17T10:04:00Z", 101.6),
        ("2026-08-17T10:05:00Z", 102.0),
    ]


def test_candidates_share_one_realized_outcome_but_keep_separate_errors():
    experiment = _experiment()
    outcome = evaluate_parallel_forecast_experiment_v2(experiment, _points())

    assert outcome is not None
    assert outcome.outcome_key == experiment.outcome_key
    assert outcome.reference_price == 100.0
    assert outcome.realized_terminal_price == 102.0
    assert outcome.realized_return == pytest.approx(0.02)
    assert outcome.technical.realized_return == outcome.technical_context.realized_return
    assert outcome.technical.predicted_return == experiment.technical.predicted_return
    assert outcome.technical_context.predicted_return == experiment.technical_context.predicted_return
    assert outcome.technical.absolute_error != outcome.technical_context.absolute_error


def test_unmatured_path_produces_no_partial_score():
    outcome = evaluate_parallel_forecast_experiment_v2(
        _experiment(),
        [
            ("2026-08-17T10:00:00Z", 100.0),
            ("2026-08-17T10:02:00Z", 101.0),
        ],
    )
    assert outcome is None


def test_long_market_gap_uses_existing_active_time_semantics():
    experiment = _experiment()
    outcome = evaluate_parallel_forecast_experiment_v2(
        experiment,
        [
            ("2026-08-17T10:00:00Z", 100.0),
            ("2026-08-17T10:01:00Z", 100.2),
            ("2026-08-18T10:00:00Z", 100.4),
            ("2026-08-18T10:01:00Z", 100.6),
            ("2026-08-18T10:02:00Z", 100.8),
            ("2026-08-18T10:03:00Z", 101.0),
            ("2026-08-18T10:04:00Z", 101.2),
        ],
    )
    assert outcome is not None
    assert outcome.matured_at == "2026-08-18T10:04:00+00:00"


def test_store_freezes_outcome_once_and_scores_both_candidates(tmp_path):
    resolved = evaluate_parallel_forecast_experiment_v2(_experiment(), _points())
    assert resolved is not None
    store = ParallelForecastOutcomeStoreV2(tmp_path / "parallel.db")

    assert store.save(resolved) is True
    assert store.save(resolved) is False
    assert store.is_resolved(resolved.outcome_key) is True

    with store._connect() if hasattr(store, "_connect") else __import__("database").connect(store.path) as db:
        outcomes = db.execute("SELECT COUNT(*) AS n FROM pg_v2_parallel_forecast_outcomes").fetchone()["n"]
        scores = db.execute("SELECT COUNT(*) AS n FROM pg_v2_parallel_forecast_scores").fetchone()["n"]
    assert outcomes == 1
    assert scores == 2
