from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging

from realtime_market_data import RealtimeMarketDataStore, minute_start, utc
from saxo_provider import SaxoClient, SaxoInstrument
from saxo_streaming import (
    BACKFILL_TIMEOUT_SECONDS,
    SaxoRealtimeService,
    _backfill_client,
    bars_from_chart_frame,
)


LOGGER = logging.getLogger("pricegauger.realtime_gap_repair")
REPAIR_LOOKBACK_HOURS = 36
REPAIR_PAGE_SIZE = 1200
REPAIR_MAX_PAGES = 4


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
    """Refetch a bounded recent 1m window and fill any holes in canonical storage.

    Repair is deliberately window-based rather than "since latest bar" so gaps that
    sit *behind* a newer live segment are repaired as well. Existing canonical bars
    are safely overwritten by the same Saxo provider key.
    """
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
        bars = bars_from_chart_frame(
            frame,
            market=market,
            instrument=instrument,
            now=current,
        )
        bars = [bar for bar in bars if utc(bar.bar_time) >= cursor]
        if not bars:
            break

        for bar in bars:
            store.save_bar(bar)
            saved += 1

        newest = max(utc(bar.bar_time) for bar in bars)
        next_cursor = newest + timedelta(minutes=1)
        if next_cursor >= current or next_cursor <= cursor:
            break
        cursor = next_cursor

    return saved


class GapRepairingSaxoRealtimeService(SaxoRealtimeService):
    """Saxo realtime service that repairs recent canonical holes on reconnect."""

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
