from __future__ import annotations

import pytest

from forecast_contracts import ForecastSnapshot
from forecast_learning import (
    ForecastOutcomeStore,
    evaluate_forecast,
    realized_path,
    realized_progress_path,
    refresh_forecast_outcomes,
)
from forecast_store import ForecastStore
from state_contracts import ComponentStatus, MarketStateSnapshot
from state_runtime_store import StateRuntimeStore


def _forecast(**overrides):
    values = dict(
        forecast_id="forecast:test-learning",
        market="Gold",
        as_of="2026-08-07T20:00:00+00:00",
        reference_price=100.0,
        direction="LONG_BIAS",
        direction_score=0.6,
        confidence=0.7,
        expected_move_low_pct=0.5,
        expected_move_high_pct=2.0,
        horizon_hours=1.0,
        time_scale="HOURS",
        decision_snapshot_id="decision:learning",
        information_snapshot_id="information:learning",
        market_snapshot_id="market:learning",
        status="DEGRADED",
        missing_inputs=("calibrated_move_model",),
        status_reason="test",
    )
    values.update(overrides)
    return ForecastSnapshot(**values)


def _market_state(snapshot_id: str, as_of: str, price: float) -> MarketStateSnapshot:
    return MarketStateSnapshot(
        snapshot_id=snapshot_id,
        market="Gold",
        as_of=as_of,
        price=price,
        direction_score=0.0,
        volatility_score=0.2,
        momentum_score=0.0,
        price_confirmation=0.0,
        regime="TEST",
        component=ComponentStatus(
            observed_at=as_of,
            age_seconds=0,
            freshness="FRESH",
            provider="test",
            instrument="Gold",
            engine_version="test",
        ),
    )


def test_forecast_learning_uses_active_market_time_across_weekend(tmp_path):
    db = tmp_path / "learning.db"
    forecast = _forecast()
    ForecastStore(db).save(forecast)
    StateRuntimeStore(db).save_market_states(
        [
            _market_state("m1", "2026-08-07T20:15:00+00:00", 99.5),
            _market_state("m2", "2026-08-07T20:30:00+00:00", 100.2),
            _market_state("m3", "2026-08-10T08:45:00+00:00", 100.6),
            _market_state("m4", "2026-08-10T09:00:00+00:00", 100.9),
            _market_state("m5", "2026-08-10T09:15:00+00:00", 101.2),
        ]
    )

    outcome = evaluate_forecast(db, forecast)
    overlay = realized_progress_path(db, forecast)

    assert outcome.status == "COMPLETE"
    assert outcome.progress == 1.0
    assert outcome.sample_count == 5
    assert outcome.realized_move_pct == 1.2
    assert outcome.direction_hit is True
    assert outcome.interval_hit is True
    assert outcome.mfe_pct == 1.2
    assert outcome.mae_pct == -0.5
    assert overlay[0] == (0.0, 0.0)
    assert overlay[-1][0] == 1.0
    assert overlay[-1][1] == pytest.approx(1.2)


def test_refresh_persists_partial_outcomes_and_realized_path(tmp_path):
    db = tmp_path / "learning.db"
    forecast = _forecast(horizon_hours=4.0)
    ForecastStore(db).save(forecast)
    StateRuntimeStore(db).save_market_states(
        [
            _market_state("m1", "2026-08-07T20:15:00+00:00", 100.2),
            _market_state("m2", "2026-08-07T20:30:00+00:00", 100.4),
        ]
    )

    refreshed = refresh_forecast_outcomes(db)
    stored = ForecastOutcomeStore(db).load_all(market="Gold")
    path = realized_path(db, forecast)
    history = ForecastStore(db).load_all(market="Gold")

    assert len(refreshed) == 1
    assert refreshed[0].status == "PARTIAL"
    assert 0.0 < refreshed[0].progress < 1.0
    assert stored[0].forecast_id == forecast.forecast_id
    assert stored[0].interval_hit is None
    assert history[0].forecast_id == forecast.forecast_id
    assert path == (
        ("2026-08-07T20:15:00+00:00", 100.2),
        ("2026-08-07T20:30:00+00:00", 100.4),
    )
