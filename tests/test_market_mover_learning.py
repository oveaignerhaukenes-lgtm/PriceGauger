from __future__ import annotations

from datetime import datetime, timedelta, timezone

from market_mover_learning import (
    MarketMoverOutcomeStore,
    evaluate_market_mover,
    refresh_market_mover_outcomes,
)
from state_contracts import ComponentStatus, MarketMoverAlert, MarketStateSnapshot
from state_runtime_store import StateRuntimeStore


def _state(stamp: datetime, price: float, index: int) -> MarketStateSnapshot:
    iso = stamp.astimezone(timezone.utc).isoformat()
    return MarketStateSnapshot(
        snapshot_id=f"market:gold:mover-learning:{index}",
        market="Gold",
        as_of=iso,
        price=price,
        direction_score=0.1,
        volatility_score=0.2,
        momentum_score=0.1,
        price_confirmation=0.1,
        regime="NEUTRAL · MEDIUM · test",
        component=ComponentStatus(
            observed_at=iso,
            age_seconds=0,
            freshness="FRESH",
            provider="test",
            instrument="Gold",
            engine_version="test-v1",
        ),
    )


def _alert(created_at: datetime, *, direction: str = "UP") -> MarketMoverAlert:
    stamp = created_at.astimezone(timezone.utc).isoformat()
    return MarketMoverAlert(
        alert_id="market-mover:test:gold",
        event_cluster_id="cluster:test",
        created_at=stamp,
        updated_at=stamp,
        status="ACTIVE",
        severity="ALERT",
        headline="Test mover",
        summary="Synthetic test mover",
        confirmation_status="CONFIRMED",
        source_quality=0.8,
        novelty=0.9,
        market="Gold",
        expected_direction=direction,
        expected_move_low_pct=0.8 if direction == "UP" else -2.0,
        expected_move_high_pct=2.0 if direction == "UP" else -0.8,
        horizon_hours=2.0,
        state_delta=0.7 if direction == "UP" else -0.7,
        price_confirmation=0.4,
        context_multiplier=1.2,
        rationale="test",
    )


def test_market_mover_outcome_tracks_peak_and_time_to_peak(tmp_path):
    path = tmp_path / "mover-learning.db"
    runtime = StateRuntimeStore(path)
    start = datetime(2026, 8, 10, 10, 0, tzinfo=timezone.utc)
    alert = _alert(start)
    runtime.save_alert(alert)
    runtime.save_market_states(
        [
            _state(start, 100.0, 0),
            _state(start + timedelta(minutes=20), 100.5, 1),
            _state(start + timedelta(minutes=50), 101.2, 2),
            _state(start + timedelta(minutes=80), 100.7, 3),
        ]
    )

    outcome = evaluate_market_mover(path, alert, evaluated_at=start + timedelta(minutes=90))

    assert outcome.status == "PARTIAL"
    assert round(outcome.observed_move_pct or 0.0, 2) == 1.20
    assert outcome.time_to_peak_minutes == 50
    assert outcome.direction_hit is True
    assert outcome.expected_range_reached is True
    assert outcome.peak_within_expected_interval is True


def test_market_mover_outcome_is_complete_after_horizon(tmp_path):
    path = tmp_path / "mover-complete.db"
    runtime = StateRuntimeStore(path)
    start = datetime(2026, 8, 10, 10, 0, tzinfo=timezone.utc)
    alert = _alert(start, direction="DOWN")
    runtime.save_alert(alert)
    runtime.save_market_states(
        [
            _state(start, 100.0, 0),
            _state(start + timedelta(minutes=30), 99.6, 1),
            _state(start + timedelta(minutes=75), 98.9, 2),
            _state(start + timedelta(minutes=110), 99.2, 3),
        ]
    )

    outcome = evaluate_market_mover(path, alert, evaluated_at=start + timedelta(hours=3))

    assert outcome.status == "COMPLETE"
    assert round(outcome.observed_move_pct or 0.0, 2) == -1.10
    assert outcome.time_to_peak_minutes == 75
    assert outcome.direction_hit is True
    assert outcome.expected_range_reached is True
    assert outcome.peak_within_expected_interval is True


def test_refresh_persists_separate_market_mover_population(tmp_path):
    path = tmp_path / "mover-refresh.db"
    runtime = StateRuntimeStore(path)
    start = datetime.now(timezone.utc) - timedelta(minutes=30)
    alert = _alert(start)
    runtime.save_alert(alert)
    runtime.save_market_states(
        [
            _state(start, 100.0, 0),
            _state(start + timedelta(minutes=10), 100.9, 1),
        ]
    )

    outcomes = refresh_market_mover_outcomes(path)
    stored = MarketMoverOutcomeStore(path).load_all(market="Gold")

    assert len(outcomes) == 1
    assert len(stored) == 1
    assert stored[0].alert_id == alert.alert_id
    assert stored[0].market == "Gold"
