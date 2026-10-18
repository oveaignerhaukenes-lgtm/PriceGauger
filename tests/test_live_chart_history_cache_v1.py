"""Pure regression tests for the presentation-only history cache."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from realtime_market_data import RealtimeBar1m
from tradingdesk_ui.charts.lightweight.live_chart_history_cache_v1 import LiveChartHistoryCache


BASE = datetime(2026, 10, 16, 20, 0, tzinfo=timezone.utc)


def bar(minutes, close=100.0):
    return RealtimeBar1m(
        market="Gold", bar_time=(BASE + timedelta(minutes=minutes)).isoformat(),
        open=float(close), high=float(close), low=float(close), close=float(close),
        sample_count=1, provider="canonical-v2", uic=1, asset_type="CfdOnFutures",
        symbol="Gold",
    )


class FakeStore:
    def __init__(self, data):
        self.bars = list(data)
        self.ranges = []
        self.latest_reads = 0

    def load_range(self, *, market, start, end, limit):
        assert market == "Gold"
        self.ranges.append((start, end, limit))
        return [
            row for row in self.bars
            if start <= datetime.fromisoformat(row.bar_time) <= end
        ][:limit]

    def load_latest_bar(self, *, market):
        assert market == "Gold"
        self.latest_reads += 1
        return self.bars[-1] if self.bars else None


def load(cache, store, *, tick=0.0, timeframe="1m", identity=("1", "CFD")):
    return cache.load(
        market="Gold", timeframe=timeframe, window_hours=6,
        instrument_identity=identity, store=store,
        now=BASE + timedelta(minutes=25), tick=tick,
    )


def test_unchanged_ticks_only_read_indexed_latest_and_reuse_resampled_tuple():
    store = FakeStore([bar(0, 1), bar(1, 2)])
    cache = LiveChartHistoryCache(full_refresh_seconds=60)
    first, raw = load(cache, store)
    second, raw_again = load(cache, store, tick=1)
    assert first is second
    assert raw is raw_again
    assert len(store.ranges) == 1
    assert store.latest_reads == 1
    assert [item.close for item in second] == [1, 2]


def test_newly_closed_bar_and_same_minute_correction_refresh_tail():
    store = FakeStore([bar(0, 1), bar(1, 2)])
    cache = LiveChartHistoryCache()
    load(cache, store)
    store.bars.append(bar(2, 3))
    closed, _ = load(cache, store, tick=1)
    assert [item.close for item in closed] == [1, 2, 3]
    assert len(store.ranges) == 2
    assert store.ranges[1][2] == 300  # overlapping bounded tail
    store.bars[-1] = replace(store.bars[-1], close=9, high=9)
    corrected, _ = load(cache, store, tick=2)
    assert [item.close for item in corrected] == [1, 2, 9]
    assert len(store.ranges) == 3


def test_periodic_full_reload_catches_old_backfills_and_retains_order():
    store = FakeStore([bar(0, 1), bar(2, 3)])
    cache = LiveChartHistoryCache(full_refresh_seconds=60)
    load(cache, store)
    store.bars.insert(1, bar(1, 2))
    unchanged, _ = load(cache, store, tick=59)
    assert [item.close for item in unchanged] == [1, 3]
    backfilled, _ = load(cache, store, tick=60)
    assert [item.close for item in backfilled] == [1, 2, 3]
    assert len(store.ranges) == 2


def test_timeframe_and_instrument_are_independent_cache_dimensions():
    store = FakeStore([bar(0, 1), bar(1, 2), bar(2, 3)])
    cache = LiveChartHistoryCache()
    minute, _ = load(cache, store, timeframe="1m")
    grouped, _ = load(cache, store, tick=1, timeframe="5m")
    assert len(grouped) == 1
    assert grouped[0].close == 3
    assert len(minute) == 3
    assert len(store.ranges) == 1
    load(cache, store, tick=2, identity=("2", "CFD"))
    assert len(store.ranges) == 2


def test_very_large_gap_falls_back_to_full_read():
    store = FakeStore([bar(0, 1)])
    cache = LiveChartHistoryCache()
    load(cache, store)
    store.bars.append(bar(130, 2))
    load(cache, store, tick=1)
    assert len(store.ranges) == 2
    assert store.ranges[1][2] == 20000


def test_empty_source_rechecks_latest_for_first_completed_bar():
    store = FakeStore([])
    cache = LiveChartHistoryCache()
    first, _ = load(cache, store)
    assert first == ()
    store.bars.append(bar(2, 3))
    second, _ = load(cache, store, tick=1)
    assert len(second) == 1
    assert len(store.ranges) == 2
