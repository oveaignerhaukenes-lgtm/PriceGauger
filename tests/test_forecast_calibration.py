from __future__ import annotations

from forecast_calibration import build_forecast_calibration
from forecast_contracts import forecast_from_decision
from forecast_learning import ForecastOutcome
from state_contracts import ComponentStatus, DecisionStateSnapshot, MarketStateSnapshot


def _outcome(index: int, *, market: str = "Gold", horizon: float = 4.0, realized: float = 1.0, expected: float = 2.0):
    return ForecastOutcome(
        forecast_id=f"forecast:{index}",
        market=market,
        forecast_as_of=f"2026-08-10T{index:02d}:00:00+00:00",
        evaluated_at="2026-08-10T12:00:00+00:00",
        status="COMPLETE",
        progress=1.0,
        horizon_hours=horizon,
        reference_price=100.0,
        last_observed_at="2026-08-10T12:00:00+00:00",
        last_price=101.0,
        realized_move_pct=realized,
        expected_move_low_pct=expected * 0.35,
        expected_move_high_pct=expected,
        interval_hit=True,
        direction_hit=True,
        max_up_pct=realized,
        max_down_pct=0.0,
        mfe_pct=realized,
        mae_pct=0.0,
        sample_count=240,
    )


def _decision() -> DecisionStateSnapshot:
    return DecisionStateSnapshot(
        snapshot_id="decision:test",
        market="Gold",
        as_of="2026-08-10T12:00:00+00:00",
        previous_snapshot_id="",
        direction="LONG_BIAS",
        direction_score=0.4,
        confidence=0.5,
        expected_move_low_pct=None,
        expected_move_high_pct=None,
        horizon_hours=4.0,
        information_snapshot_id="information:test",
        market_snapshot_id="market:test",
        change_from_previous=0.0,
        contributing_event_ids=("event:test",),
        status_reason="test",
    )


def _market_state() -> MarketStateSnapshot:
    component = ComponentStatus(
        observed_at="2026-08-10T12:00:00+00:00",
        age_seconds=0,
        freshness="FRESH",
        provider="test",
        instrument="Gold",
        engine_version="test",
    )
    return MarketStateSnapshot(
        snapshot_id="market:test",
        market="Gold",
        as_of="2026-08-10T12:00:00+00:00",
        price=4400.0,
        direction_score=0.2,
        volatility_score=0.2,
        momentum_score=0.2,
        price_confirmation=0.2,
        regime="test",
        component=component,
    )


def test_calibration_needs_enough_same_market_same_horizon_samples():
    outcomes = [_outcome(i) for i in range(5)]
    assert build_forecast_calibration(outcomes, market="Gold", horizon_hours=4.0) is None

    outcomes.append(_outcome(5, market="Brent"))
    outcomes.append(_outcome(6, horizon=1.0))
    assert build_forecast_calibration(outcomes, market="Gold", horizon_hours=4.0) is None


def test_calibration_shrinks_repeated_overprediction_conservatively():
    outcomes = [_outcome(i, realized=1.0, expected=2.0) for i in range(12)]
    calibration = build_forecast_calibration(outcomes, market="Gold", horizon_hours=4.0)

    assert calibration is not None
    assert calibration.sample_count == 12
    assert calibration.raw_factor == 0.5
    assert 0.5 < calibration.applied_factor < 1.0


def test_calibrated_forecast_records_and_applies_feedback_factor():
    forecast = forecast_from_decision(
        _decision(),
        market_state=_market_state(),
        calibration_factor=0.75,
        calibration_sample_count=18,
        calibration_version="forecast-calibration-v1",
    )

    # Gold baseline at score 0.4 is +0.35%..+1.00%; feedback scales both by 0.75.
    assert forecast.expected_move_low_pct == 0.2625
    assert forecast.expected_move_high_pct == 0.75
    assert forecast.calibration_factor == 0.75
    assert forecast.calibration_sample_count == 18
    assert forecast.calibration_version == "forecast-calibration-v1"
    assert "calibrated_move_model" not in forecast.missing_inputs


def test_uncalibrated_baseline_remains_explicitly_degraded():
    forecast = forecast_from_decision(_decision(), market_state=_market_state())
    assert "calibrated_move_model" in forecast.missing_inputs
    assert forecast.calibration_factor is None
