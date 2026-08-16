from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from instrument_registry_v2 import InstrumentSourceV2, list_subscribed_sources_v2
from saxo_provider import SaxoInstrument


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


def load_runtime_instruments_v2(
    configured: Mapping[str, SaxoInstrument],
) -> RuntimeInstrumentSetV2:
    """Overlay explicit v2 collection subscriptions on the legacy configured feed set.

    The v2 registry is authoritative for a market once it has an enabled Saxo
    subscription. PriceGauger's current realtime/Technical-Core bridge remains
    single-feed-per-market, so multiple enabled instruments for the same canonical
    market fail closed instead of silently mixing two price series.
    """
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
