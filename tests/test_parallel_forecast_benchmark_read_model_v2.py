from __future__ import annotations

import pytest

from parallel_forecast_benchmark_read_model_v2 import load_benchmark_aggregates_v2
from parallel_forecast_outcome_store_v2 import ParallelForecastOutcomeStoreV2
from parallel_forecast_outcome_v2 import CandidateOutcomeScoreV2, ParallelForecastOutcomeV2


def _outcome(*, key: str, market: str, horizon: int, tech_error: float, ctx_error: float, tech_dir: bool, ctx_dir: bool, tech_interval: bool, ctx_interval: bool):
    return ParallelForecastOutcomeV2(
        outcome_key=key,
        market=market,
        forecast_as_of="2026-08-17T00:00:00+00:00",
        horizon_seconds=horizon,
        matured_at="2026-08-17T00:05:00+00:00",
        reference_price=100.0,
        realized_terminal_price=101.0,
        realized_return=0.01,
        technical=CandidateOutcomeScoreV2(
            candidate_kind="TECH_ONLY",
            predicted_return=0.0,
            realized_return=0.01,
            signed_error=tech_error,
            absolute_error=tech_error,
            direction_hit=tech_dir,
            interval_hit=tech_interval,
        ),
        technical_context=CandidateOutcomeScoreV2(
            candidate_kind="TECH_CONTEXT",
            predicted_return=0.0,
            realized_return=0.01,
            signed_error=ctx_error,
            absolute_error=ctx_error,
            direction_hit=ctx_dir,
            interval_hit=ctx_interval,
        ),
    )


def test_read_model_aggregates_only_matched_pairs(tmp_path):
    db_path = str(tmp_path / "pg.db")
    store = ParallelForecastOutcomeStoreV2(db_path)
    store.save(_outcome(key="a", market="GOLD", horizon=300, tech_error=0.03, ctx_error=0.01, tech_dir=False, ctx_dir=True, tech_interval=False, ctx_interval=True))
    store.save(_outcome(key="b", market="GOLD", horizon=300, tech_error=0.01, ctx_error=0.02, tech_dir=True, ctx_dir=True, tech_interval=True, ctx_interval=False))

    aggregates = load_benchmark_aggregates_v2(db_path=db_path)
    assert len(aggregates) == 1
    row = aggregates[0]
    assert row.market == "GOLD"
    assert row.horizon_seconds == 300
    assert row.sample_size == 2
    assert row.technical_mae == pytest.approx(0.02)
    assert row.technical_context_mae == pytest.approx(0.015)
    assert row.mae_delta == pytest.approx(-0.005)
    assert row.technical_direction_hit_rate == pytest.approx(0.5)
    assert row.technical_context_direction_hit_rate == pytest.approx(1.0)
    assert row.direction_hit_rate_delta == pytest.approx(0.5)
    assert row.technical_interval_hit_rate == pytest.approx(0.5)
    assert row.technical_context_interval_hit_rate == pytest.approx(0.5)
    assert row.interval_hit_rate_delta == pytest.approx(0.0)
    assert (row.context_wins, row.ties, row.context_losses) == (1, 0, 1)


def test_read_model_groups_by_market_and_horizon_and_filters(tmp_path):
    db_path = str(tmp_path / "pg.db")
    store = ParallelForecastOutcomeStoreV2(db_path)
    store.save(_outcome(key="gold5", market="GOLD", horizon=300, tech_error=0.02, ctx_error=0.01, tech_dir=True, ctx_dir=True, tech_interval=True, ctx_interval=True))
    store.save(_outcome(key="gold15", market="GOLD", horizon=900, tech_error=0.02, ctx_error=0.02, tech_dir=True, ctx_dir=False, tech_interval=True, ctx_interval=False))
    store.save(_outcome(key="silver5", market="SILVER", horizon=300, tech_error=0.01, ctx_error=0.02, tech_dir=True, ctx_dir=True, tech_interval=True, ctx_interval=True))

    assert len(load_benchmark_aggregates_v2(db_path=db_path)) == 3
    filtered = load_benchmark_aggregates_v2(db_path=db_path, market="GOLD", horizon_seconds=300)
    assert len(filtered) == 1
    assert filtered[0].market == "GOLD"
    assert filtered[0].horizon_seconds == 300
    assert filtered[0].context_wins == 1


def test_empty_benchmark_returns_empty_read_model(tmp_path):
    db_path = str(tmp_path / "pg.db")
    ParallelForecastOutcomeStoreV2(db_path)
    assert load_benchmark_aggregates_v2(db_path=db_path) == ()


def test_invalid_horizon_filter_is_rejected(tmp_path):
    db_path = str(tmp_path / "pg.db")
    ParallelForecastOutcomeStoreV2(db_path)
    with pytest.raises(ValueError, match="horizon_seconds"):
        load_benchmark_aggregates_v2(db_path=db_path, horizon_seconds=0)
