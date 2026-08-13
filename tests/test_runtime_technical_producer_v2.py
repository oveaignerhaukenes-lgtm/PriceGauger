from __future__ import annotations

from datetime import datetime, timedelta, timezone

from runtime_technical_producer_v2 import build_runtime_frames_v2, produce_technical_runtime_v2


class FakeHistoryStore:
    def __init__(self, points):
        self.points = tuple(points)
        self.calls = []

    def load_range(self, *, market, start, end, limit):
        self.calls.append((market, start, end, limit))
        return self.points


def _points(count: int = 900):
    start = datetime(2026, 8, 13, 0, 0, tzinfo=timezone.utc)
    rows = []
    price = 60.0
    for index in range(count):
        price += 0.01
        rows.append(((start + timedelta(minutes=index)).isoformat(), price))
    return rows


def test_runtime_frames_are_derived_from_canonical_one_minute_points():
    frames = build_runtime_frames_v2(_points(180))

    assert set(frames) == {"1m", "5m", "15m", "30m", "1h", "4h"}
    assert len(frames["1m"]) == 180
    assert frames["30m"].iloc[-1]["close"] == frames["1m"].iloc[-1]["close"]
    assert frames["1m"].iloc[-1]["high"] == frames["1m"].iloc[-1]["close"]


def test_runtime_producer_builds_state_and_requested_baselines():
    points = _points()
    store = FakeHistoryStore(points)
    as_of = points[-1][0]

    produced = produce_technical_runtime_v2(
        market="Silver",
        history_store=store,
        as_of=as_of,
        lookback_hours=24,
        horizons=(300, 3600),
    )

    assert produced.market == "Silver"
    assert produced.technical_state.market == "Silver"
    assert produced.technical_state.primary_timeframe == "30m"
    assert set(produced.baselines) == {300, 3600}
    assert all(item.technical_state == produced.technical_state for item in produced.baselines.values())
    assert store.calls and store.calls[0][0] == "Silver"


def test_same_input_produces_same_state_and_forecasts():
    points = _points()
    as_of = points[-1][0]

    first = produce_technical_runtime_v2(
        market="Gold",
        history_store=FakeHistoryStore(points),
        as_of=as_of,
        horizons=(900, 3600),
    )
    second = produce_technical_runtime_v2(
        market="Gold",
        history_store=FakeHistoryStore(points),
        as_of=as_of,
        horizons=(900, 3600),
    )

    assert first.technical_state == second.technical_state
    assert first.baselines == second.baselines
