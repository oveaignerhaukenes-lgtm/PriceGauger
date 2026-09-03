from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from database import connect, using_postgres
from db_workspace_persistence_v2 import technical_state_identity_v2
from feature_snapshot_v1 import persist_feature_snapshot_v1
from instrument_registry_v2 import (
    ensure_instrument_source_v2,
    ensure_instrument_v2,
    ensure_market_v2,
    resolve_instrument_source_v2,
    set_collection_subscription_v2,
)
from market_history_store import MarketHistoryStore
from parallel_forecast_runtime_v2 import run_parallel_forecast_runtime_cycle_v2
from realtime_market_data import RealtimeMarketDataStore
from recipe_registry_v2 import TA_ONLY_V1, TECHNICAL_CORE_RECIPE_V2_1
from runtime_health_v2 import RuntimeHealthV2, freshness_health_v2, record_runtime_health_v2
from runtime_technical_producer_v2 import (
    persist_produced_runtime_v2,
    produce_technical_runtime_v2,
)
from saxo_provider import SaxoInstrument


LOGGER = logging.getLogger("pricegauger.v2_live_technical")
DEFAULT_INTERVAL_SECONDS = 60
SERVICE_NAME = "v2-technical-runtime"


@dataclass(frozen=True, slots=True)
class LiveTechnicalCycleSummaryV2:
    attempted: int
    produced: int
    failed: int


def ensure_db_v2_schema() -> None:
    """Apply the idempotent DB v2 schema to the authoritative PostgreSQL backend."""
    if not using_postgres():
        raise RuntimeError("live v2 technical runtime requires PostgreSQL")
    schema_path = Path(__file__).resolve().with_name("db_v2_schema.sql")
    script = schema_path.read_text(encoding="utf-8")
    with connect() as db:
        db.executescript(script)


def _instrument_display_name(market: str, instrument: SaxoInstrument) -> str:
    label = (instrument.description or instrument.symbol or market).strip()
    expiry = f" {instrument.expiry}" if instrument.expiry else ""
    return f"{label}{expiry} [{instrument.asset_type}:{instrument.uic}]"


def register_saxo_instrument_v2(*, market: str, instrument: SaxoInstrument) -> int:
    """Resolve the canonical v2 identity or register a legacy configured feed once.

    Explicit Product Explorer onboarding owns existing provider identities. The
    runtime must reuse that identity rather than creating a second instrument row
    with a runtime-generated display label.
    """
    try:
        existing = resolve_instrument_source_v2(
            provider="saxo",
            provider_instrument_id=str(instrument.uic),
        )
    except LookupError:
        existing = None

    if existing is not None:
        if existing.asset_type and str(existing.asset_type) != str(instrument.asset_type):
            raise ValueError(
                "registered Saxo provider identity has different AssetType; refusing runtime remap"
            )
        if existing.market_name != market:
            raise ValueError(
                f"registered Saxo source {instrument.uic} belongs to canonical market "
                f"{existing.market_name!r}, not runtime market {market!r}"
            )
        set_collection_subscription_v2(instrument_id=existing.instrument_id, enabled=True)
        return existing.market_id

    market_id = ensure_market_v2(
        name=market,
        category=instrument.asset_type or "market",
    )
    instrument_id = ensure_instrument_v2(
        market_id=market_id,
        instrument_type=instrument.asset_type or "unknown",
        display_name=_instrument_display_name(market, instrument),
    )
    ensure_instrument_source_v2(
        instrument_id=instrument_id,
        provider="saxo",
        provider_instrument_id=str(instrument.uic),
        asset_type=instrument.asset_type,
        symbol=instrument.symbol or None,
        price_multiplier=instrument.price_multiplier,
        metadata={
            "asset": instrument.asset,
            "description": instrument.description,
            "expiry": instrument.expiry,
        },
    )
    set_collection_subscription_v2(instrument_id=instrument_id, enabled=True)
    return market_id


def _record_failure(market: str, exc: Exception) -> None:
    record_runtime_health_v2(
        RuntimeHealthV2(
            service=SERVICE_NAME,
            stage=market,
            status="DEGRADED",
            detail=f"{type(exc).__name__}: {exc}",
            age_seconds=None,
        )
    )


def _feed_delay_by_market(db_path: str) -> dict[str, float]:
    try:
        statuses = RealtimeMarketDataStore(db_path).load_statuses()
    except Exception:
        return {}
    return {
        status.market: max(0.0, float(status.delay_minutes))
        for status in statuses
        if status.delay_minutes is not None
    }


def _canonical_freshness_health(
    *,
    market: str,
    db_path: str,
    fallback_as_of: str,
    delay_minutes: float = 0.0,
) -> RuntimeHealthV2:
    """Measure canonical 1m freshness relative to the feed's known entitlement delay.

    Provider-delayed data is healthy when it arrives consistently at the entitled
    delay. Technical Core ``as_of`` is not a feed freshness clock.
    """
    latest = CanonicalMarketBarStoreV2(db_path).load_latest(market=market)
    observed_at = latest.bar_time if latest is not None else fallback_as_of
    delay = max(0.0, float(delay_minutes))
    effective_now = datetime.now(timezone.utc) - timedelta(minutes=delay)
    health = freshness_health_v2(
        service=SERVICE_NAME,
        stage=market,
        observed_at=observed_at,
        now=effective_now,
    )
    source = "canonical 1m" if latest is not None else "technical snapshot fallback"
    delay_text = f" · feed delay={delay:g}m" if delay > 0.0 else ""
    return RuntimeHealthV2(
        service=health.service,
        stage=health.stage,
        status=health.status,
        detail=(
            f"{source} effective age={health.age_seconds:.1f}s{delay_text}"
            if health.age_seconds is not None
            else f"{source} unavailable{delay_text}"
        ),
        age_seconds=health.age_seconds,
    )


def run_live_technical_cycle_v2(
    *,
    instruments: Mapping[str, SaxoInstrument],
    db_path: str = "pricegauger.db",
    ensure_schema: bool = True,
) -> LiveTechnicalCycleSummaryV2:
    """Produce and persist one TA-only v2 snapshot for every active runtime market."""
    if ensure_schema:
        ensure_db_v2_schema()
    history_store = MarketHistoryStore(db_path)
    delay_by_market = _feed_delay_by_market(db_path)
    produced_count = 0
    failed_count = 0

    for market, instrument in tuple(instruments.items()):
        try:
            market_id = register_saxo_instrument_v2(market=market, instrument=instrument)
            instrument_source = resolve_instrument_source_v2(
                provider="saxo",
                provider_instrument_id=str(instrument.uic),
            )
            produced = produce_technical_runtime_v2(
                market=market,
                history_store=history_store,
            )
            persist_produced_runtime_v2(
                produced,
                market_id=market_id,
                technical_recipe_id=TECHNICAL_CORE_RECIPE_V2_1.recipe_id,
                analysis_recipe_id=TA_ONLY_V1.recipe_id,
                analysis_recipe_name=TA_ONLY_V1.name,
                analysis_recipe_version=TA_ONLY_V1.version,
            )
            technical_state_id = technical_state_identity_v2(
                market_id=market_id,
                as_of=produced.technical_state.as_of,
                technical_recipe_id=TECHNICAL_CORE_RECIPE_V2_1.recipe_id,
            )
            persist_feature_snapshot_v1(
                market_id=market_id,
                instrument_id=instrument_source.instrument_id,
                state=produced.technical_state,
                source_technical_state_id=technical_state_id,
            )
            try:
                benchmark = run_parallel_forecast_runtime_cycle_v2(
                    produced,
                    history_store=history_store,
                    db_path=db_path,
                )
                LOGGER.info(
                    "v2 parallel benchmark market=%s attempted=%d inserted=%d resolved=%d",
                    market,
                    benchmark.experiments_attempted,
                    benchmark.experiments_inserted,
                    benchmark.outcomes_resolved,
                )
            except Exception as exc:
                # Benchmark collection is observational. It must never make the
                # authoritative Technical Core runtime unhealthy.
                LOGGER.warning(
                    "v2 parallel benchmark failed market=%s: %s",
                    market,
                    exc,
                    exc_info=True,
                )
            record_runtime_health_v2(
                _canonical_freshness_health(
                    market=market,
                    db_path=db_path,
                    fallback_as_of=produced.as_of,
                    delay_minutes=delay_by_market.get(market, 0.0),
                )
            )
            produced_count += 1
        except Exception as exc:
            failed_count += 1
            _record_failure(market, exc)
            LOGGER.warning("v2 TA-only production failed market=%s: %s", market, exc, exc_info=True)

    return LiveTechnicalCycleSummaryV2(
        attempted=len(instruments),
        produced=produced_count,
        failed=failed_count,
    )


def run_live_technical_forever_v2(
    *,
    instruments: Mapping[str, SaxoInstrument],
    db_path: str = "pricegauger.db",
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
) -> None:
    """Continuously refresh persisted TA-only v2 state from canonical market history."""
    interval = max(15, int(interval_seconds))
    ensure_db_v2_schema()
    while True:
        try:
            summary = run_live_technical_cycle_v2(
                instruments=instruments,
                db_path=db_path,
                ensure_schema=False,
            )
            LOGGER.info(
                "v2 TA-only cycle attempted=%d produced=%d failed=%d",
                summary.attempted,
                summary.produced,
                summary.failed,
            )
        except Exception as exc:
            LOGGER.exception("v2 TA-only runtime cycle failed before market production: %s", exc)
        time.sleep(interval)