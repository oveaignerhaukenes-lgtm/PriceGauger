from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import threading
import time

from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from database import using_postgres
from instrument_registry_v2 import InstrumentSourceV2, list_subscribed_sources_v2
from realtime_gap_repair import repair_recent_market_history
from realtime_market_data import RealtimeMarketDataStore
from saxo_provider import SaxoInstrument, configured_client


LOGGER = logging.getLogger("pricegauger.saxo_discovered_history_seed_v2")
DISCOVERY_ORIGIN = "SAXO_OPEN_POSITION"
SEED_LOOKBACK_HOURS = 24 * 10
SEED_MAX_PAGES = 10
SEED_PAGE_SIZE = 1200
SEED_MIN_1M_BARS = 1200
SEED_RETRY_SECONDS = 300.0
SEED_SCHEDULE_MIN_INTERVAL_SECONDS = 60.0
_LAST_ATTEMPT_MONO: dict[int, float] = {}
_SEED_THREAD_LOCK = threading.Lock()
_SEED_THREAD: threading.Thread | None = None
_LAST_SEED_SCHEDULE_MONO = 0.0


@dataclass(frozen=True, slots=True)
class DiscoveredHistorySeedSummaryV2:
    candidates: int
    already_ready: int
    attempted: int
    bars_saved: int
    ready_after_seed: int
    failed: int


def _is_discovered_source(source: InstrumentSourceV2) -> bool:
    return str((source.metadata or {}).get("discovery_origin") or "").strip().upper() == DISCOVERY_ORIGIN


def _instrument(source: InstrumentSourceV2) -> SaxoInstrument:
    if not source.asset_type:
        raise ValueError("discovered Saxo source is missing AssetType")
    uic = int(source.provider_instrument_id)
    if uic <= 0:
        raise ValueError("discovered Saxo source has invalid UIC")
    metadata = source.metadata or {}
    multiplier = 1.0 if source.price_multiplier is None else float(source.price_multiplier)
    if multiplier <= 0:
        raise ValueError("discovered Saxo source has invalid price multiplier")
    return SaxoInstrument(
        asset=source.market_name,
        uic=uic,
        asset_type=str(source.asset_type),
        symbol=str(source.symbol or ""),
        description=str(metadata.get("description") or source.display_name or ""),
        expiry=(str(metadata.get("expiry")) if metadata.get("expiry") else None),
        price_multiplier=multiplier,
    )


def _recent_bar_count(
    source: InstrumentSourceV2,
    *,
    store: CanonicalMarketBarStoreV2,
    now: datetime,
) -> int:
    start = now - timedelta(hours=SEED_LOOKBACK_HOURS)
    bars = store.load_instrument_range(
        instrument_id=source.instrument_id,
        start=start,
        end=now,
        limit=SEED_MIN_1M_BARS,
    )
    return len(bars)


def _retry_due(instrument_id: int, *, now_mono: float) -> bool:
    previous = _LAST_ATTEMPT_MONO.get(int(instrument_id))
    return previous is None or now_mono - previous >= SEED_RETRY_SECONDS


def seed_discovered_saxo_history_once_v2(
    client=None,
    *,
    db_path: str = "pricegauger.db",
    now: datetime | None = None,
    monotonic_now: float | None = None,
) -> DiscoveredHistorySeedSummaryV2:
    """Deep-seed newly discovered Saxo products for closed-30m strategy readiness.

    Normal reconnect repair intentionally remains light (36h). A newly discovered
    product can arrive on a weekend or after a holiday, where 36 calendar hours may
    contain too few tradable minutes for closed-30m MACD 12/26/9. Only sources that
    originated from open-position discovery are eligible for this deeper one-time
    seed. Once at least ``SEED_MIN_1M_BARS`` exact canonical bars exist, this path is
    cheap/no-op for the rolling window.

    The potentially expensive history writes are intended to run through
    ``start_discovered_saxo_history_seed_v2`` so registry/stream startup is never
    blocked. This function itself remains synchronous for deterministic testing and
    explicit callers.

    This function grants no execution authority and performs only Saxo GET/history
    reads plus canonical bar persistence.
    """
    if not using_postgres():
        return DiscoveredHistorySeedSummaryV2(0, 0, 0, 0, 0, 0)

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    current = current.astimezone(timezone.utc)
    mono = time.monotonic() if monotonic_now is None else float(monotonic_now)

    sources = tuple(
        source
        for source in list_subscribed_sources_v2(provider="saxo")
        if _is_discovered_source(source)
    )
    if not sources:
        return DiscoveredHistorySeedSummaryV2(0, 0, 0, 0, 0, 0)

    canonical = CanonicalMarketBarStoreV2(db_path)
    ready = 0
    pending: list[InstrumentSourceV2] = []
    for source in sources:
        try:
            if _recent_bar_count(source, store=canonical, now=current) >= SEED_MIN_1M_BARS:
                ready += 1
            elif _retry_due(source.instrument_id, now_mono=mono):
                pending.append(source)
        except Exception as exc:
            LOGGER.warning(
                "discovered-history readiness check failed market=%s instrument_id=%s: %s",
                source.market_name,
                source.instrument_id,
                exc,
                exc_info=True,
            )

    if not pending:
        return DiscoveredHistorySeedSummaryV2(len(sources), ready, 0, 0, 0, 0)

    client = client or configured_client()
    if client is None:
        return DiscoveredHistorySeedSummaryV2(len(sources), ready, 0, 0, 0, len(pending))

    realtime = RealtimeMarketDataStore(db_path)
    attempted = 0
    saved_total = 0
    ready_after = 0
    failed = 0

    for source in pending:
        _LAST_ATTEMPT_MONO[int(source.instrument_id)] = mono
        attempted += 1
        try:
            instrument = _instrument(source)
            saved = repair_recent_market_history(
                store=realtime,
                client=client,
                market=source.market_name,
                instrument=instrument,
                now=current,
                lookback_hours=SEED_LOOKBACK_HOURS,
                page_size=SEED_PAGE_SIZE,
                max_pages=SEED_MAX_PAGES,
            )
            saved_total += int(saved)
            count = _recent_bar_count(source, store=canonical, now=current)
            if count >= SEED_MIN_1M_BARS:
                ready_after += 1
                LOGGER.info(
                    "discovered Saxo history seeded market=%s uic=%s instrument_id=%s saved=%d recent_bars=%d",
                    source.market_name,
                    source.provider_instrument_id,
                    source.instrument_id,
                    saved,
                    count,
                )
            else:
                LOGGER.warning(
                    "discovered Saxo history still insufficient market=%s uic=%s saved=%d recent_bars=%d required=%d; retry throttled",
                    source.market_name,
                    source.provider_instrument_id,
                    saved,
                    count,
                    SEED_MIN_1M_BARS,
                )
        except Exception as exc:
            failed += 1
            LOGGER.warning(
                "discovered Saxo history seed failed market=%s uic=%s: %s",
                source.market_name,
                source.provider_instrument_id,
                exc,
                exc_info=True,
            )

    return DiscoveredHistorySeedSummaryV2(
        candidates=len(sources),
        already_ready=ready,
        attempted=attempted,
        bars_saved=saved_total,
        ready_after_seed=ready_after,
        failed=failed,
    )


def _run_scheduled_seed(*, db_path: str) -> None:
    try:
        summary = seed_discovered_saxo_history_once_v2(db_path=db_path)
        if summary.attempted or summary.failed:
            LOGGER.info(
                "discovered Saxo history seed cycle candidates=%d ready=%d attempted=%d saved=%d ready_after=%d failed=%d",
                summary.candidates,
                summary.already_ready,
                summary.attempted,
                summary.bars_saved,
                summary.ready_after_seed,
                summary.failed,
            )
    except Exception as exc:
        LOGGER.warning("discovered Saxo history seed cycle failed: %s", exc, exc_info=True)


def start_discovered_saxo_history_seed_v2(
    *,
    db_path: str = "pricegauger.db",
    monotonic_now: float | None = None,
) -> bool:
    """Schedule at most one non-blocking deep-seed job per process.

    Registry refresh is latency-sensitive because it gates realtime subscription
    startup/resubscription. Thousands of historical 1m writes must therefore never
    execute inline on that path. Strategy consumers remain fail-closed until the
    background seed has persisted enough exact canonical history.
    """
    global _SEED_THREAD, _LAST_SEED_SCHEDULE_MONO

    mono = time.monotonic() if monotonic_now is None else float(monotonic_now)
    with _SEED_THREAD_LOCK:
        if _SEED_THREAD is not None and _SEED_THREAD.is_alive():
            return False
        if (
            _LAST_SEED_SCHEDULE_MONO > 0
            and mono - _LAST_SEED_SCHEDULE_MONO < SEED_SCHEDULE_MIN_INTERVAL_SECONDS
        ):
            return False
        _LAST_SEED_SCHEDULE_MONO = mono
        thread = threading.Thread(
            target=_run_scheduled_seed,
            kwargs={"db_path": db_path},
            name="pricegauger-discovered-history-seed",
            daemon=True,
        )
        _SEED_THREAD = thread
        thread.start()
        return True


__all__ = [
    "DISCOVERY_ORIGIN",
    "SEED_LOOKBACK_HOURS",
    "SEED_MAX_PAGES",
    "SEED_MIN_1M_BARS",
    "SEED_PAGE_SIZE",
    "SEED_SCHEDULE_MIN_INTERVAL_SECONDS",
    "DiscoveredHistorySeedSummaryV2",
    "seed_discovered_saxo_history_once_v2",
    "start_discovered_saxo_history_seed_v2",
]
