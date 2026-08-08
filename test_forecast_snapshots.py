from __future__ import annotations

from forecast_contracts import ForecastSnapshot, forecast_from_decision
from forecast_store import ForecastStore
from state_contracts import ComponentStatus, DecisionStateSnapshot, MarketStateSnapshot


def _decision(**overrides):
    values = dict(
        snapshot_id="decision:gold:1",
        market="Gold",
        as_of="2026-08-08T22:00:00+00:00",
        previous_snapshot_id="",
        direction="LONG_BIAS",
        direction_score=0.64,
        confidence=0.71,
        expected_move_low_pct=0.6,
        expected_move_high_pct=1.4,
        horizon_hours=4.0,
        information_snapshot_id="information:1",
        market_snapshot_id="market:gold:1",
        change_from_previous=0.12,
        contributing_event_ids=("101",),
        status_reason="News and technical state agree.",
    )
    values.update(overrides)
    return DecisionStateSnapshot(**values)


def _market_state():
    return MarketStateSnapshot(
        snapshot_id="market:gold:1",
        market="Gold",
        as_of="2026-08-08T22:00:00+00:00",
        price=4200.0,
        direction_score=0.4,
        volatility_score=0.3,
        momentum_score=0.5,
        price_confirmation=0.4,
        regime="UPTREND",
        component=ComponentStatus(
            observed_at="2026-08-08T22:00:00+00:00",
            age_seconds=0,
            freshness="FRESH",
            provider="saxo",
            instrument="Gold",
            engine_version="technical-v1",
        ),
    )


def test_ready_forecast_captures_reference_and_horizon():
    forecast = forecast_from_decision(_decision(), market_state=_market_state())

    assert forecast.status == "READY"
    assert forecast.reference_price == 4200.0
    assert forecast.time_scale == "HOURS"
    assert forecast.expected_move_low_pct == 0.6
    assert forecast.expected_move_high_pct == 1.4
    assert forecast.missing_inputs == ()


def test_degraded_forecast_records_missing_inputs_without_dropping_forecast():
    forecast = forecast_from_decision(
        _decision(market_snapshot_id="market-confirmation-pending"),
        market_state=None,
        additional_missing_inputs=("news_context",),
    )

    assert forecast.status == "DEGRADED"
    assert forecast.reference_price is None
    assert "reference_price" in forecast.missing_inputs
    assert "technical_market_state" in forecast.missing_inputs
    assert "news_context" in forecast.missing_inputs
    assert forecast.horizon_hours == 4.0


def test_provisional_forecast_is_still_persisted_for_calibration(tmp_path):
    decision = _decision(
        expected_move_low_pct=None,
        expected_move_high_pct=None,
        horizon_hours=None,
        market_snapshot_id="market-confirmation-pending",
    )
    forecast = forecast_from_decision(decision, market_state=None)
    store = ForecastStore(tmp_path / "forecast.db")

    assert forecast.status == "PROVISIONAL"
    store.save(forecast)
    loaded = store.load_latest(market="Gold")

    assert loaded == forecast
    assert "expected_move_interval" in loaded.missing_inputs
    assert "forecast_horizon" in loaded.missing_inputs


def test_store_keeps_historical_snapshots_per_decision(tmp_path):
    store = ForecastStore(tmp_path / "history.db")
    first = forecast_from_decision(_decision(), market_state=_market_state())
    second = ForecastSnapshot(
        **{
            **first.to_record(),
            "forecast_id": "forecast:second",
            "as_of": "2026-08-08T23:00:00+00:00",
            "decision_snapshot_id": "decision:gold:2",
            "confidence": 0.8,
            "missing_inputs": (),
        }
    )

    assert store.save_all((first, second)) == 2
    latest = store.load_latest(market="Gold")

    assert latest is not None
    assert latest.forecast_id == "forecast:second"
    assert latest.confidence == 0.8
