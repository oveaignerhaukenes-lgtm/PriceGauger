"""Bounded read-only history cache for the 1-second TradingDesk/Live Chart UI.

The LIVE strategy and Saxo execution runtimes never use this module. The cache
only changes presentation queries; an overlapping tail and periodic full reload
catch completed bars, recent corrections, delayed backfills and instrument changes.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from threading import RLock
from time import monotonic
from typing import Any

from realtime_market_data import RealtimeBar1m, RealtimeMarketDataStore
from saxo_chart_live import FormingCandle1m, FormingCandleStore, forming_candle_event_age_seconds
from trading_desk import ChartBar, TIMEFRAME_MINUTES, resample_bars, utc


@dataclass
class _HistoryEntry:
    raw: tuple[RealtimeBar1m, ...]
    fetched_at: float
    closed: dict[str, tuple[ChartBar, ...]] = field(default_factory=dict)


class LiveChartHistoryCache:
    """Share immutable historical reads across clients, not browser sessions."""

    def __init__(self, *, max_entries: int = 24, full_refresh_seconds: float = 60.0):
        self._lock = RLock()
        self._entries: OrderedDict[tuple[Any, ...], _HistoryEntry] = OrderedDict()
        self._store: RealtimeMarketDataStore | None = None
        self.max_entries = max(1, int(max_entries))
        self.full_refresh_seconds = max(1.0, float(full_refresh_seconds))

    def _get_store(self) -> RealtimeMarketDataStore:
        if self._store is None:
            self._store = RealtimeMarketDataStore()
        return self._store

    @staticmethod
    def _full_read(store, *, market: str, hours: int, now: datetime) -> tuple[RealtimeBar1m, ...]:
        return tuple(store.load_range(
            market=market, start=now - timedelta(hours=hours), end=now, limit=20000,
        ))

    def load(
        self, *, market: str, timeframe: str, window_hours: int,
        instrument_identity: tuple[str, str] = ("", ""),
        store=None, now: datetime | None = None, tick: float | None = None,
    ) -> tuple[tuple[ChartBar, ...], tuple[RealtimeBar1m, ...]]:
        current = utc(now or datetime.now(timezone.utc))
        elapsed = monotonic() if tick is None else float(tick)
        hours = int(window_hours)
        key = (str(market), hours, str(instrument_identity[0]), str(instrument_identity[1]))

        with self._lock:
            source = store if store is not None else self._get_store()
            entry = self._entries.get(key)
            must_reload = (
                entry is None or elapsed < entry.fetched_at
                or elapsed - entry.fetched_at >= self.full_refresh_seconds
            )
            if must_reload:
                entry = _HistoryEntry(
                    raw=self._full_read(source, market=market, hours=hours, now=current),
                    fetched_at=elapsed,
                )
            else:
                # Indexed latest-bar lookup instead of reading the whole 6-48h range
                # every second. The next full read is bounded by the 60s TTL.
                latest = source.load_latest_bar(market=market)
                if latest is not None:
                    previous = entry.raw[-1] if entry.raw else None
                    prev_at = utc(previous.bar_time) if previous else None
                    latest_at = utc(latest.bar_time)
                    changed = (
                        previous is None
                        or latest_at > prev_at
                        or (latest_at == prev_at and latest != previous)
                    )
                    if prev_at is not None and latest_at < prev_at:
                        # The physical source or instrument may have been replaced.
                        must_reload = True
                    elif changed and prev_at is None:
                        must_reload = True
                    elif changed and prev_at is not None:
                        if latest_at - prev_at > timedelta(minutes=120):
                            must_reload = True
                        else:
                            tail_from = prev_at - timedelta(minutes=3)
                            tail = tuple(source.load_range(
                                market=market, start=tail_from, end=current, limit=300,
                            ))
                            if tail:
                                # Preserve source ordering and any multi-source rows,
                                # replacing the overlapped window exactly as a fresh
                                # load_range result would.
                                retained = tuple(
                                    bar for bar in entry.raw if utc(bar.bar_time) < tail_from
                                )
                                entry = _HistoryEntry(
                                    raw=retained + tail, fetched_at=entry.fetched_at,
                                )
                            else:
                                must_reload = True

                if must_reload:
                    entry = _HistoryEntry(
                        raw=self._full_read(source, market=market, hours=hours, now=current),
                        fetched_at=elapsed,
                    )

            self._entries[key] = entry
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)

            if timeframe not in entry.closed:
                entry.closed[timeframe] = resample_bars(entry.raw, timeframe=timeframe)
            return entry.closed[timeframe], entry.raw


_HISTORY = LiveChartHistoryCache()


@lru_cache(maxsize=1)
def _forming_store() -> FormingCandleStore:
    # Store methods create their own DB connections; do not cache a connection.
    return FormingCandleStore()


def load_live_test_snapshot_v1(*, market, timeframe, window_hours, instrument):
    """Canonical closed history + fresh forming candle for both UI pages."""
    closed, raw = _HISTORY.load(
        market=market, timeframe=timeframe, window_hours=window_hours,
        instrument_identity=(
            str(instrument.provider_instrument_id), str(instrument.asset_type),
        ),
    )
    try:
        candidate = _forming_store().load(market=market)
    except Exception:
        candidate = None

    forming = None
    if (
        candidate is not None
        and str(candidate.uic) == str(instrument.provider_instrument_id)
        and candidate.asset_type == instrument.asset_type
        and (forming_candle_event_age_seconds(candidate) or 0.0) <= 8.0
    ):
        minutes = TIMEFRAME_MINUTES[timeframe]
        if minutes == 1:
            forming = candidate
        else:
            current_at = utc(candidate.bar_time)
            bucket_seconds = minutes * 60
            bucket_epoch = int(current_at.timestamp()) - (int(current_at.timestamp()) % bucket_seconds)
            bucket_at = datetime.fromtimestamp(bucket_epoch, tz=timezone.utc)
            bucket_raw = [item for item in raw if bucket_at <= utc(item.bar_time) < current_at]
            open_price = float(bucket_raw[0].open) if bucket_raw else float(candidate.open)
            highs = [float(item.high) for item in bucket_raw] + [float(candidate.high)]
            lows = [float(item.low) for item in bucket_raw] + [float(candidate.low)]
            forming = FormingCandle1m(
                market=candidate.market, bar_time=bucket_at.isoformat(),
                open=open_price, high=max(highs), low=min(lows), close=float(candidate.close),
                volume=candidate.volume, provider=candidate.provider, uic=int(candidate.uic),
                asset_type=candidate.asset_type, symbol=candidate.symbol,
                delayed_by_minutes=candidate.delayed_by_minutes,
                source_event_at=candidate.source_event_at, updated_at=candidate.updated_at,
            )
    return closed, forming
