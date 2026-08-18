from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import threading
import time

from canonical_market_bars_v2 import QUALITY_BACKFILL
from realtime_market_data import RealtimeMarketDataStore, RealtimeQuote, minute_start, utc
from saxo_provider import SaxoClient, SaxoInstrument
from saxo_streaming import (
    BACKFILL_TIMEOUT_SECONDS,
    SaxoRealtimeService,
    SaxoStreamMessage,
    _backfill_client,
    bars_from_chart_frame,
)

LOGGER = logging.getLogger("pricegauger.realtime_gap_repair")
REPAIR_LOOKBACK_HOURS = 36
REPAIR_PAGE_SIZE = 1200
REPAIR_MAX_PAGES = 4
STALE_REPAIR_INTERVAL_SECONDS = 60.0
STALE_QUOTE_AFTER_SECONDS = 90.0
STALE_REPAIR_LOOKBACK_HOURS = 1
STALE_REPAIR_PAGE_SIZE = 120


def repair_recent_market_history(
    *,
    store: RealtimeMarketDataStore,
    client: SaxoClient,
    market: str,
    instrument: SaxoInstrument,
    now: datetime | None = None,
    lookback_hours: int = REPAIR_LOOKBACK_HOURS,
    page_size: int = REPAIR_PAGE_SIZE,
    max_pages: int = REPAIR_MAX_PAGES,
) -> int:
    current = minute_start(now or datetime.now(timezone.utc))
    cursor = current - timedelta(hours=max(1, int(lookback_hours)))
    saved = 0
    for _ in range(max(1, int(max_pages))):
        frame = client.chart(
            instrument,
            horizon_minutes=1,
            count=max(1, min(1200, int(page_size))),
            time=cursor,
            mode="From",
        )
        bars = bars_from_chart_frame(frame, market=market, instrument=instrument, now=current)
        bars = [bar for bar in bars if utc(bar.bar_time) >= cursor]
        if not bars:
            break
        for bar in bars:
            store.save_bar(bar, quality_flags=QUALITY_BACKFILL)
            saved += 1
        newest = max(utc(bar.bar_time) for bar in bars)
        next_cursor = newest + timedelta(minutes=1)
        if next_cursor >= current or next_cursor <= cursor:
            break
        cursor = next_cursor
    return saved


class GapRepairingSaxoRealtimeService(SaxoRealtimeService):
    """Saxo stream with bounded chart repair when quote delivery goes stale.

    The WebSocket remains the primary realtime source.  Chart repair is only
    scheduled for markets whose quote stream has not produced an observation in
    the stale window.  This keeps canonical 1m history moving when Saxo leaves a
    subscription transport alive but does not deliver usable quote deltas.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._stale_repair_lock = threading.Lock()
        self._stale_repair_thread: threading.Thread | None = None
        self._last_stale_repair_started = 0.0

    def _consume_quote(self, quote: RealtimeQuote) -> None:
        previous = self._status_cache.get(quote.market)
        first_observation = previous is None or previous.last_quote_at is None
        super()._consume_quote(quote)
        if first_observation:
            # subscribe_all persists SUBSCRIBED immediately before consuming the
            # initial Snapshot.  The base 15s write throttle would otherwise hide
            # that first quote from persisted health/probe state if no later delta
            # arrives.  Persist the transition once; normal quote writes stay
            # throttled afterwards.
            current = self._status_cache.get(quote.market)
            if current is not None:
                self.store.save_status(current)
                self._last_status_write[quote.market] = time.monotonic()

    def _market_quote_is_stale(self, market: str, *, now: datetime) -> bool:
        status = self._status_cache.get(market)
        if status is None or not status.last_quote_at:
            return True
        try:
            observed = utc(status.last_quote_at)
        except (TypeError, ValueError):
            return True
        return (now - observed).total_seconds() >= STALE_QUOTE_AFTER_SECONDS

    def _run_stale_repair(self) -> None:
        if not self._stale_repair_lock.acquire(blocking=False):
            return
        try:
            now = datetime.now(timezone.utc)
            stale_markets = tuple(
                market for market in self.instruments if self._market_quote_is_stale(market, now=now)
            )
            if not stale_markets:
                return
            client = _backfill_client(self.client)
            total = 0
            repaired: list[str] = []
            for market in stale_markets:
                instrument = self.instruments[market]
                try:
                    saved = repair_recent_market_history(
                        store=self.store,
                        client=client,
                        market=market,
                        instrument=instrument,
                        now=now,
                        lookback_hours=STALE_REPAIR_LOOKBACK_HOURS,
                        page_size=STALE_REPAIR_PAGE_SIZE,
                        max_pages=1,
                    )
                    total += saved
                    repaired.append(f"{market}:{saved}")
                except Exception as exc:
                    LOGGER.warning(
                        "Saxo stale-stream repair failed market=%s: %s",
                        market,
                        exc,
                        exc_info=True,
                    )
            LOGGER.info(
                "Saxo stale-stream repair complete markets=%s bars=%d",
                ",".join(repaired) or "none",
                total,
            )
        finally:
            self._stale_repair_lock.release()

    def _start_stale_repair_if_due(self) -> bool:
        now_mono = time.monotonic()
        if now_mono - self._last_stale_repair_started < STALE_REPAIR_INTERVAL_SECONDS:
            return False
        if self._stale_repair_thread is not None and self._stale_repair_thread.is_alive():
            return False
        self._last_stale_repair_started = now_mono
        self._stale_repair_thread = threading.Thread(
            target=self._run_stale_repair,
            name="pricegauger-saxo-stale-repair",
            daemon=True,
        )
        self._stale_repair_thread.start()
        return True

    def handle_message(
        self,
        message: SaxoStreamMessage,
        *,
        received_at: str | None = None,
    ) -> None:
        super().handle_message(message, received_at=received_at)
        # Heartbeats prove the transport is alive, but they do not prove that
        # market subscriptions are delivering prices.  Use any incoming frame as
        # a cheap cadence source for the bounded stale-market fallback.
        self._start_stale_repair_if_due()

    def _run_backfill(self) -> None:
        if not self._backfill_lock.acquire(blocking=False):
            return
        try:
            client = _backfill_client(self.client)
            total = 0
            for market, instrument in self.instruments.items():
                try:
                    total += repair_recent_market_history(
                        store=self.store,
                        client=client,
                        market=market,
                        instrument=instrument,
                    )
                except Exception as exc:
                    LOGGER.warning(
                        "Saxo recent-history repair failed market=%s: %s",
                        market,
                        exc,
                        exc_info=True,
                    )
            LOGGER.info(
                "Saxo recent-history repair complete bars=%d lookback_hours=%d timeout_seconds=%.0f",
                total,
                REPAIR_LOOKBACK_HOURS,
                BACKFILL_TIMEOUT_SECONDS,
            )
        finally:
            self._backfill_lock.release()
