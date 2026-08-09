from __future__ import annotations

from datetime import datetime, timedelta, timezone

from market_history_store import MarketHistoryStore
from state_contracts import ComponentStatus, MarketStateSnapshot
from state_runtime_store import StateRuntimeStore


def _state(stamp: datetime, price: float, index: int) -> MarketStateSnapshot:
    iso = stamp.astimezone(timezone.utc).isoformat()
    return MarketStateSnapshot(
        snapshot_id=f"market:gold:range:{index}",
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


def test_load_range_returns_only_points_inside_requested_clock_window(tmp_path):
    path = tmp_path / "range.db"
    runtime = StateRuntimeStore(path)
    start = datetime(2026, 8, 9, 8, 0, tzinfo=timezone.utc)
    runtime.save_market_states(
        [_state(start + timedelta(minutes=5 * index), 4200.0 + index, index) for index in range(6)]
    )

    points = MarketHistoryStore(path).load_range(
        market="Gold",
        start=start + timedelta(minutes=5),
        end=start + timedelta(minutes=20),
    )

    assert [price for _, price in points] == [4201.0, 4202.0, 4203.0, 4204.0]
    assert points[0][0] == "2026-08-09T08:05:00+00:00"
    assert points[-1][0] == "2026-08-09T08:20:00+00:00"
