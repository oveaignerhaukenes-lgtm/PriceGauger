from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from database import connect, using_postgres
from instrument_registry_v2 import (
    ensure_instrument_source_v2,
    ensure_instrument_v2,
    ensure_market_v2,
    resolve_instrument_source_v2,
    set_collection_subscription_v2,
)
from market_history_store import MarketHistoryStore
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


def run_live_technical_cycle_v2(
    *,
    instruments: Mapping[str, SaxoInstrument],
    db_path: str = "pricegauger.db",
    ensure_schema: bool = True,
) -> LiveTechnicalCycleSummaryV2:
    """Produce and persist one TA-only v2 snapshot for every active runtime market.

    The existing ``realtime_bars_1m`` / ``MarketHistoryStore`` path remains the
    canonical market-history bridge during this controlled v2 cutover. Runtime
    instrument discovery is driven by enabled v2 collection subscriptions; this
    producer consumes the resulting market set and does not create a second feed.
    """
    if ensure_schema:
        ensure_db_v2_schema()
    history_store = MarketHistoryStore(db_path)
    produced_count = 0
    failed_count = 0

    for market, instrument in tuple(instruments.items()):
        try:
            market_id = register_saxo_instrument_v2(market=market, instrument=instrument)
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
            record_runtime_health_v2(
                freshness_health_v2(
                    service=SERVICE_NAME,
                    stage=market,
                    observed_at=produced.as_of,
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
