from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Mapping

from futures_rollover_schema_v1 import ensure_futures_rollover_audit_ready_v1
from futures_rollover_v1 import resolve_saxo_futures_rollovers_once_v1
from instrument_registry_v2 import InstrumentSourceV2, list_subscribed_sources_v2
from saxo_discovered_history_seed_v2 import seed_discovered_saxo_history_once_v2
from saxo_open_position_discovery_v2 import discover_open_saxo_positions_once_v2
from saxo_provider import SaxoInstrument


LOGGER = logging.getLogger("pricegauger.runtime_subscription_bridge_v2")


@dataclass(frozen=True, slots=True)
class RuntimeInstrumentSetV2:
    instruments: dict[str, SaxoInstrument]
    registry_markets: tuple[str, ...]


def _saxo_instrument(source: InstrumentSourceV2) -> SaxoInstrument:
    if not source.asset_type:
        raise ValueError(
            f"subscribed Saxo source {source.provider_instrument_id} is missing AssetType"
        )
    try:
        uic = int(source.provider_instrument_id)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"subscribed Saxo source has invalid UIC: {source.provider_instrument_id!r}"
        ) from exc
    if uic <= 0:
        raise ValueError(f"subscribed Saxo source has invalid UIC: {uic}")
    multiplier = 1.0 if source.price_multiplier is None else float(source.price_multiplier)
    if multiplier <= 0:
        raise ValueError(f"subscribed Saxo source {uic} has invalid price_multiplier")
    metadata = source.metadata or {}
    return SaxoInstrument(
        asset=source.market_name,
        uic=uic,
        asset_type=str(source.asset_type),
        symbol=str(source.symbol or ""),
        description=str(metadata.get("description") or source.display_name or ""),
        expiry=(str(metadata.get("expiry")) if metadata.get("expiry") else None),
        price_multiplier=multiplier,
    )


def _discover_open_positions_best_effort() -> None:
    """Populate the registry from externally opened Saxo positions without blocking feeds."""
    try:
        summary = discover_open_saxo_positions_once_v2()
    except Exception as exc:
        LOGGER.warning("Saxo open-position discovery cycle failed: %s", exc, exc_info=True)
        return
    if summary.onboarded or summary.subscriptions_reactivated or summary.failed:
        LOGGER.info(
            "Saxo open-position discovery observed=%d known=%d reactivated=%d onboarded=%d failed=%d",
            summary.observed_products,
            summary.already_subscribed,
            summary.subscriptions_reactivated,
            summary.onboarded,
            summary.failed,
        )


def _prepare_futures_rollover_audit_best_effort() -> None:
    """Ensure rollover audit schema exists and recover any partial prior switch."""
    try:
        recovered = ensure_futures_rollover_audit_ready_v1()
    except Exception as exc:
        # Without the audit boundary we deliberately skip automatic rollover rather
        # than allow another unaudited collection identity transition.
        raise RuntimeError(f"futures rollover audit preparation failed: {exc}") from exc
    if recovered:
        LOGGER.warning("Recovered futures rollover audit rows=%d", recovered)


def _resolve_futures_rollovers_best_effort() -> None:
    """Move collection subscriptions to current futures contracts, never execution authority."""
    try:
        summary = resolve_saxo_futures_rollovers_once_v1()
    except Exception as exc:
        LOGGER.warning("Saxo futures rollover cycle failed: %s", exc, exc_info=True)
        return
    if summary.rolled or summary.failed:
        LOGGER.info(
            "Saxo futures rollover checked=%d eligible=%d rolled=%d unchanged=%d failed=%d",
            summary.checked,
            summary.eligible,
            summary.rolled,
            summary.unchanged,
            summary.failed,
        )


def _seed_discovered_history_best_effort() -> None:
    """Give newly discovered/rolled products enough exact history for strategy bootstrap."""
    try:
        summary = seed_discovered_saxo_history_once_v2()
    except Exception as exc:
        LOGGER.warning("Saxo discovered-history seed cycle failed: %s", exc, exc_info=True)
        return
    if summary.attempted or summary.failed:
        LOGGER.info(
            "Saxo discovered-history seed candidates=%d ready=%d attempted=%d saved=%d ready_after=%d failed=%d",
            summary.candidates,
            summary.already_ready,
            summary.attempted,
            summary.bars_saved,
            summary.ready_after_seed,
            summary.failed,
        )


def load_runtime_instruments_v2(
    configured: Mapping[str, SaxoInstrument],
) -> RuntimeInstrumentSetV2:
    """Overlay explicit v2 collection subscriptions on the legacy configured feed set.

    Registry refresh first discovers externally opened products, prepares/reconciles the
    rollover audit boundary, then resolves expiring subscribed futures to a new immutable
    collection identity. Only afterwards does it seed exact history for any newly active
    product. Rollover never changes an AutoManager or AutoTrader LIVE controller UIC;
    execution keeps its separate close/FLAT/admission gate.

    PriceGauger's realtime/Technical-Core bridge remains single-feed-per-market, so
    multiple enabled instruments for the same canonical market fail closed instead of
    silently mixing two price series.
    """
    _discover_open_positions_best_effort()
    _prepare_futures_rollover_audit_best_effort()
    _resolve_futures_rollovers_best_effort()
    _seed_discovered_history_best_effort()

    result = dict(configured)
    sources = list_subscribed_sources_v2(provider="saxo")
    by_market: dict[str, list[InstrumentSourceV2]] = {}
    for source in sources:
        by_market.setdefault(source.market_name, []).append(source)

    ambiguous = {market: rows for market, rows in by_market.items() if len(rows) > 1}
    if ambiguous:
        detail = ", ".join(
            f"{market} ({len(rows)} enabled instruments)" for market, rows in sorted(ambiguous.items())
        )
        raise RuntimeError(
            "v2 realtime bridge requires exactly one enabled collection instrument per canonical market; "
            f"ambiguous: {detail}"
        )

    for market, rows in by_market.items():
        result[market] = _saxo_instrument(rows[0])

    return RuntimeInstrumentSetV2(
        instruments=result,
        registry_markets=tuple(sorted(by_market)),
    )


def instrument_signature_v2(instruments: Mapping[str, SaxoInstrument]) -> tuple[tuple[object, ...], ...]:
    return tuple(
        sorted(
            (
                market,
                int(instrument.uic),
                str(instrument.asset_type),
                str(instrument.symbol or ""),
                float(instrument.price_multiplier),
            )
            for market, instrument in instruments.items()
        )
    )
