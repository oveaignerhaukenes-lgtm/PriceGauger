from __future__ import annotations

from datetime import datetime, timedelta, timezone

from market_history_store import MarketHistoryStore
from state_contracts import ComponentStatus, MarketStateSnapshot
from state_runtime_store import StateRuntimeStore


def _market_state(stamp: datetime, price: float, index: int) -> MarketStateSnapshot:
    iso = stamp.astimezone(timezone.utc).isoformat()
    return MarketStateSnapshot(
        snapshot_id=f"market:gold:{index}",
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


def test_history_window_uses_last_active_hours_across_weekend(tmp_path):
    path = tmp_path / "history.db"
    runtime = StateRuntimeStore(path)
    start = datetime(2026, 8, 7, 15, 30, tzinfo=timezone.utc)
    states = [
        _market_state(start + timedelta(minutes=30 * index), 4300.0 + index, index)
        for index in range(10)
    ]
    runtime.save_market_states(states)

    history = MarketHistoryStore(path).load_window(
        market="Gold",
        as_of="2026-08-09T22:00:00+00:00",
        horizon_hours=4.0,
    )

    # Weekend clock time does not erase Friday's last four active trading hours.
    assert len(history) == 9
    assert history[0][0] == "2026-08-07T16:00:00+00:00"
    assert history[-1][0] == "2026-08-07T20:00:00+00:00"
    assert history[-1][1] == 4309.0


def test_closed_session_gap_does_not_consume_active_history_window(tmp_path):
    path = tmp_path / "session-gap.db"
    runtime = StateRuntimeStore(path)
    thursday = datetime(2026, 8, 6, 18, 0, tzinfo=timezone.utc)
    friday = datetime(2026, 8, 7, 18, 0, tzinfo=timezone.utc)
    states = []
    index = 0
    for base in (thursday, friday):
        for offset in range(5):
            states.append(_market_state(base + timedelta(minutes=30 * offset), 4300.0 + index, index))
            index += 1
    runtime.save_market_states(states)

    history = MarketHistoryStore(path).load_window(
        market="Gold",
        as_of="2026-08-09T22:00:00+00:00",
        horizon_hours=3.5,
    )

    assert history[0][0] == "2026-08-06T18:30:00+00:00"
    assert history[-1][0] == "2026-08-07T20:00:00+00:00"
