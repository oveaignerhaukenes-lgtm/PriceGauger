from forecast_contracts import ForecastSnapshot
from forecast_error import ForecastErrorStore
from forecast_learning import refresh_forecast_outcomes
from forecast_store import ForecastStore
from state_contracts import ComponentStatus, MarketStateSnapshot
from state_runtime_store import StateRuntimeStore


def _forecast() -> ForecastSnapshot:
    return ForecastSnapshot(
        forecast_id="forecast:error-hook",
        market="Gold",
        as_of="2026-08-12T10:00:00+00:00",
        reference_price=100.0,
        direction="LONG_BIAS",
        direction_score=0.6,
        confidence=0.7,
        expected_move_low_pct=0.5,
        expected_move_high_pct=1.5,
        horizon_hours=0.25,
        time_scale="MINUTES",
        decision_snapshot_id="decision:error-hook",
        information_snapshot_id="information:error-hook",
        market_snapshot_id="market:error-hook",
        status="READY",
        missing_inputs=(),
        status_reason="test",
    )


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


def test_refresh_forecast_outcomes_freezes_completed_error_observation(tmp_path):
    db = tmp_path / "learning.db"
    ForecastStore(db).save(_forecast())
    StateRuntimeStore(db).save_market_states(
        [
            _market_state("m1", "2026-08-12T10:05:00+00:00", 100.2),
            _market_state("m2", "2026-08-12T10:10:00+00:00", 100.6),
            _market_state("m3", "2026-08-12T10:15:00+00:00", 101.0),
        ]
    )

    outcomes = refresh_forecast_outcomes(db)
    errors = ForecastErrorStore(db).load_all(market="Gold", horizon_hours=0.25)

    assert outcomes[0].status == "COMPLETE"
    assert len(errors) == 1
    assert errors[0].forecast_id == "forecast:error-hook"
    assert errors[0].classification == "IN_INTERVAL"
    assert errors[0].normalized_center_error == 0.0


def test_partial_outcome_does_not_create_error_observation(tmp_path):
    db = tmp_path / "partial.db"
    forecast = _forecast()
    ForecastStore(db).save(forecast)
    StateRuntimeStore(db).save_market_states(
        [_market_state("m1", "2026-08-12T10:05:00+00:00", 100.2)]
    )

    outcomes = refresh_forecast_outcomes(db)

    assert outcomes[0].status == "PARTIAL"
    assert ForecastErrorStore(db).load_all(market="Gold", horizon_hours=0.25) == []
