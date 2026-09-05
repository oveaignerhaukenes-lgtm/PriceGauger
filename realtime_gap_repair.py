from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import threading
import time
from typing import Any

from canonical_market_bars_v2 import QUALITY_BACKFILL, QUALITY_REALTIME
from database import connect, using_postgres
from instrument_registry_v2 import resolve_instrument_source_v2
from realtime_market_data import MinuteBarAggregator, RealtimeMarketDataStore, RealtimeQuote, minute_start, utc
from saxo_chart_live import (
    ChartStreamStatus,
    FormingCandleStore,
    chart_delay_minutes,
    create_chart_subscription,
    forming_candle_from_chart_payload,
)
from saxo_provider import SaxoClient, SaxoError, SaxoInstrument
from saxo_streaming import (
    BACKFILL_TIMEOUT_SECONDS,
    SaxoRealtimeService,
    SaxoStreamMessage,
    _backfill_client,
    _find_value,
    _should_log_count,
    bars_from_chart_frame,
    merge_delta,
)

LOGGER = logging.getLogger("pricegauger.realtime_gap_repair")
REPAIR_LOOKBACK_HOURS = 36
REPAIR_PAGE_SIZE = 1200
REPAIR_MAX_PAGES = 4
STALE_REPAIR_INTERVAL_SECONDS = 60.0
STALE_QUOTE_AFTER_SECONDS = 90.0
STALE_REPAIR_LOOKBACK_HOURS = 1
STALE_REPAIR_PAGE_SIZE = 120
STALE_AUTH_RETRY_SECONDS = 30 * 60.0
_PRICE_UPDATE_FIELDS = frozenset(
    {"Bid", "BidPrice", "Ask", "AskPrice", "LastTraded", "LastTradedPrice", "Price", "Mid"}
)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _payload_contains_price_update(payload: Any) -> bool:
    """True only when this delta itself carries a price value.

    Saxo uses delta compression. A LastUpdated-only delta must not be merged with an
    old Quote snapshot and then treated as if the old Bid/Ask were newly observed.
    """
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in _PRICE_UPDATE_FIELDS and value is not None:
                return True
            if _payload_contains_price_update(value):
                return True
    elif isinstance(payload, list):
        return any(_payload_contains_price_update(value) for value in payload)
    return False


def _normalised(value: Any) -> str:
    return "" if value is None else str(value).strip().casefold().replace("_", "").replace(" ", "")


def _payload_explicitly_stale_or_closed(payload: Any) -> bool:
    """Reject a price delta when that delta itself says the quote is not live."""
    state = _normalised(_find_value(payload, ("MarketState",)))
    if state and ("closed" in state or state in {"offline", "unavailable"}):
        return True
    price_type_bid = _normalised(_find_value(payload, ("PriceTypeBid",)))
    price_type_ask = _normalised(_find_value(payload, ("PriceTypeAsk",)))
    return price_type_bid == "oldindicative" or price_type_ask == "oldindicative"


def _snapshot_is_closed_or_old_indicative(payload: Any) -> bool:
    state = _normalised(_find_value(payload, ("MarketState",)))
    if state and ("closed" in state or state in {"offline", "unavailable"}):
        return True
    price_type_bid = _normalised(_find_value(payload, ("PriceTypeBid",)))
    price_type_ask = _normalised(_find_value(payload, ("PriceTypeAsk",)))
    return price_type_bid == "oldindicative" and price_type_ask == "oldindicative"


def _closed_snapshot_cutoff(payload: Any) -> datetime | None:
    if not _snapshot_is_closed_or_old_indicative(payload):
        return None
    raw = _find_value(payload, ("LastUpdated", "Timestamp"))
    if raw is None:
        return None
    try:
        return minute_start(utc(str(raw)))
    except (TypeError, ValueError):
        return None


def repair_closed_market_realtime_tail(
    *,
    store: RealtimeMarketDataStore,
    market: str,
    instrument: SaxoInstrument,
    cutoff: datetime,
) -> int:
    """Remove only impossible quote-built bars after Saxo's last live close stamp.

    Historical/backfill canonical rows are deliberately preserved. The repair is
    exact-product scoped and is only invoked from an explicitly closed/OldIndicative
    subscription snapshot.
    """
    cutoff_at = minute_start(cutoff)
    deleted = 0
    source = None
    if using_postgres():
        try:
            source = resolve_instrument_source_v2(
                provider="saxo",
                provider_instrument_id=str(instrument.uic),
                require_subscription=True,
            )
        except Exception as exc:
            LOGGER.warning(
                "Closed-market tail repair could not resolve canonical source market=%s uic=%s: %s",
                market,
                instrument.uic,
                exc,
            )

    with connect(store.path) as db:
        legacy = db.execute(
            """
            DELETE FROM realtime_bars_1m
            WHERE market=? AND uic=? AND provider=? AND bar_time>?
            """,
            (market, int(instrument.uic), "Saxo OpenAPI", cutoff_at.isoformat()),
        )
        if legacy.rowcount and legacy.rowcount > 0:
            deleted += int(legacy.rowcount)
        if source is not None:
            canonical = db.execute(
                """
                DELETE FROM pg_v2_market_bars_1m
                WHERE instrument_id=? AND bar_time>? AND COALESCE(quality_flags,0)=?
                """,
                (int(source.instrument_id), cutoff_at, int(QUALITY_REALTIME)),
            )
            if canonical.rowcount and canonical.rowcount > 0:
                deleted += int(canonical.rowcount)
    return deleted


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
    """Saxo stream with canonical repair plus presentation-only chart state."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._stale_repair_lock = threading.Lock()
        self._stale_repair_thread: threading.Thread | None = None
        self._last_stale_repair_started = 0.0
        self._stale_auth_retry_after: dict[str, float] = {}
        self._forming_store = FormingCandleStore(self.store.path)
        self._chart_reference_to_market: dict[str, str] = {}
        self._chart_delays: dict[str, float | None] = {}
        self._chart_actual_refresh: dict[str, int | None] = {}

    def _save_chart_status(
        self,
        *,
        market: str,
        reference_id: str,
        state: str,
        delayed_by_minutes: float | None = None,
        actual_refresh_ms: int | None = None,
        last_event_at: str | None = None,
        last_candle_at: str | None = None,
        error: str | None = None,
    ) -> None:
        previous = self._forming_store.load_status(market=market)
        self._forming_store.save_status(
            ChartStreamStatus(
                market=market,
                state=state,
                reference_id=reference_id,
                requested_refresh_ms=int(self.refresh_ms),
                actual_refresh_ms=(
                    actual_refresh_ms
                    if actual_refresh_ms is not None
                    else (None if previous is None else previous.actual_refresh_ms)
                ),
                delayed_by_minutes=(
                    delayed_by_minutes
                    if delayed_by_minutes is not None
                    else (None if previous is None else previous.delayed_by_minutes)
                ),
                last_event_at=(last_event_at if last_event_at is not None else (None if previous is None else previous.last_event_at)),
                last_candle_at=(last_candle_at if last_candle_at is not None else (None if previous is None else previous.last_candle_at)),
                error=error,
                updated_at=_iso_now(),
            )
        )

    def subscribe_all(self, context_id: str) -> None:
        super().subscribe_all(context_id)

        # A reconnect while the market is closed can return an OldIndicative quote
        # whose provider timestamp is the real closing timestamp. Purge any realtime-
        # only tail that was previously fabricated from heartbeat/LastUpdated deltas,
        # and reset the in-memory aggregator so the stale snapshot cannot later
        # overwrite the real closing OHLC when the market reopens.
        for ref, market in tuple(self.reference_to_market.items()):
            snapshot = self.snapshots.get(ref, {})
            cutoff = _closed_snapshot_cutoff(snapshot)
            if cutoff is None:
                continue
            removed = repair_closed_market_realtime_tail(
                store=self.store,
                market=market,
                instrument=self.instruments[market],
                cutoff=cutoff,
            )
            self.aggregators[market] = MinuteBarAggregator()
            previous = self._status_cache.get(market)
            self._status(
                market,
                "SUBSCRIBED",
                reference_id=ref,
                last_quote_at=None if previous is None else previous.last_quote_at,
                detail="market closed; OldIndicative snapshot is not a live quote",
            )
            LOGGER.warning(
                "Saxo closed-market realtime tail checked market=%s uic=%s cutoff=%s removed_rows=%d",
                market,
                self.instruments[market].uic,
                cutoff.isoformat(),
                removed,
            )

        self._chart_reference_to_market.clear()
        self._chart_delays.clear()
        self._chart_actual_refresh.clear()
        for index, (market, instrument) in enumerate(self.instruments.items(), start=1):
            reference_id = f"PGC{index:02d}"
            try:
                payload = create_chart_subscription(
                    self.client,
                    context_id=context_id,
                    reference_id=reference_id,
                    instrument=instrument,
                    refresh_ms=self.refresh_ms,
                )
                snapshot = payload.get("Snapshot") if isinstance(payload, dict) else None
                if not isinstance(snapshot, dict):
                    snapshot = {}
                ref = reference_id.upper()
                self._chart_reference_to_market[ref] = market
                delay = chart_delay_minutes(snapshot)
                self._chart_delays[ref] = delay
                candle = forming_candle_from_chart_payload(
                    market=market,
                    instrument=instrument,
                    payload=snapshot,
                    delayed_by_minutes=delay,
                )
                if candle is not None:
                    self._forming_store.save(candle)
                raw_actual = payload.get("RefreshRate") if isinstance(payload, dict) else None
                try:
                    actual = None if raw_actual is None else int(raw_actual)
                except (TypeError, ValueError):
                    actual = None
                self._chart_actual_refresh[ref] = actual
                self._save_chart_status(
                    market=market,
                    reference_id=reference_id,
                    state="SUBSCRIBED",
                    delayed_by_minutes=delay,
                    actual_refresh_ms=actual,
                    last_candle_at=None if candle is None else candle.updated_at,
                )
                LOGGER.info(
                    "Saxo chart stream subscribed market=%s reference=%s requested_refresh_ms=%s actual_refresh_ms=%s delay_minutes=%s snapshot_candle=%s",
                    market,
                    reference_id,
                    self.refresh_ms,
                    actual,
                    delay,
                    candle is not None,
                )
            except Exception as exc:
                self._save_chart_status(
                    market=market,
                    reference_id=reference_id,
                    state="FAILED",
                    error=f"{type(exc).__name__}: {exc}",
                )
                LOGGER.warning(
                    "Saxo chart stream subscription failed market=%s reference=%s: %s",
                    market,
                    reference_id,
                    exc,
                    exc_info=True,
                )

    def _consume_quote(self, quote: RealtimeQuote) -> None:
        previous = self._status_cache.get(quote.market)
        first_observation = previous is None or previous.last_quote_at is None
        super()._consume_quote(quote)
        if first_observation:
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

    def _stale_repair_auth_blocked(self, market: str, *, now_mono: float) -> bool:
        retry_after = self._stale_auth_retry_after.get(market)
        if retry_after is None:
            return False
        if now_mono >= retry_after:
            self._stale_auth_retry_after.pop(market, None)
            return False
        return True

    def _run_stale_repair(self) -> None:
        if not self._stale_repair_lock.acquire(blocking=False):
            return
        try:
            now = datetime.now(timezone.utc)
            now_mono = time.monotonic()
            stale_markets = tuple(
                market
                for market in self.instruments
                if self._market_quote_is_stale(market, now=now)
                and not self._stale_repair_auth_blocked(market, now_mono=now_mono)
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
                    self._stale_auth_retry_after.pop(market, None)
                    total += saved
                    repaired.append(f"{market}:{saved}")
                except SaxoError as exc:
                    if exc.status == "AUTH_FAILED" or exc.status_code in {401, 403}:
                        self._stale_auth_retry_after[market] = time.monotonic() + STALE_AUTH_RETRY_SECONDS
                        LOGGER.warning(
                            "Saxo stale-stream repair paused market=%s reason=%s retry_minutes=%.0f",
                            market,
                            exc,
                            STALE_AUTH_RETRY_SECONDS / 60.0,
                        )
                        continue
                    LOGGER.warning(
                        "Saxo stale-stream repair failed market=%s: %s",
                        market,
                        exc,
                        exc_info=True,
                    )
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
        ref = message.reference_id.upper()
        if ref.startswith("_"):
            super().handle_message(message, received_at=received_at)
            self._start_stale_repair_if_due()
            return

        chart_market = self._chart_reference_to_market.get(ref)
        if chart_market is not None:
            instrument = self.instruments[chart_market]
            delay = chart_delay_minutes(message.payload)
            if delay is not None:
                self._chart_delays[ref] = delay
            event_at = received_at or _iso_now()
            candle = forming_candle_from_chart_payload(
                market=chart_market,
                instrument=instrument,
                payload=message.payload,
                source_event_at=event_at,
                delayed_by_minutes=self._chart_delays.get(ref),
            )
            if candle is not None:
                self._forming_store.save(candle)
            self._save_chart_status(
                market=chart_market,
                reference_id=message.reference_id,
                state="STREAMING",
                delayed_by_minutes=self._chart_delays.get(ref),
                actual_refresh_ms=self._chart_actual_refresh.get(ref),
                last_event_at=event_at,
                last_candle_at=None if candle is None else candle.updated_at,
            )
            self._start_stale_repair_if_due()
            return

        price_market = self.reference_to_market.get(ref)
        if price_market is not None and isinstance(message.payload, dict):
            current = self.snapshots.get(ref, {})
            merged = merge_delta(current, message.payload)
            has_price = _payload_contains_price_update(message.payload)
            explicitly_stale = _payload_explicitly_stale_or_closed(message.payload)
            if not has_price or explicitly_stale:
                # Keep delta-compressed snapshot state current, but crucially do not
                # replay Bid/Ask inherited from an older snapshot as a new observation.
                self.snapshots[ref] = merged
                count = self._message_counts.get(ref, 0) + 1
                self._message_counts[ref] = count
                if _should_log_count(count):
                    LOGGER.info(
                        "Saxo price delta ignored market=%s reference=%s count=%d reason=%s payload_keys=%s",
                        price_market,
                        ref,
                        count,
                        "stale_or_closed" if explicitly_stale else "no_price_update",
                        ",".join(sorted(str(key) for key in message.payload)) or "none",
                    )
                self._start_stale_repair_if_due()
                return

        super().handle_message(message, received_at=received_at)
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
