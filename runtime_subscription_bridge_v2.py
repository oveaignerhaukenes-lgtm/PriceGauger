from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Mapping

from instrument_registry_v2 import InstrumentSourceV2, list_subscribed_sources_v2
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
        # Registry loading must remain available during a temporary Saxo GET or
        # Reference Data outage. Discovery is additive and grants no execution
        # authority, so a failed discovery cycle is safe to retry on the next poll.
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


def load_runtime_instruments_v2(
    configured: Mapping[str, SaxoInstrument],
) -> RuntimeInstrumentSetV2:
    """Overlay explicit v2 collection subscriptions on the legacy configured feed set.

    The registry refresh also performs best-effort discovery of currently open Saxo
    positions. Unknown exact UIC+AssetType identities are onboarded through the same
    canonical boundary as Product Explorer, but no AutoManage/execution authority is
    granted. PriceGauger's current realtime/Technical-Core bridge remains
    single-feed-per-market, so multiple enabled instruments for the same canonical
    market fail closed instead of silently mixing two price series.
    """
    _discover_open_positions_best_effort()

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
