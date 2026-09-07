from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import logging
from typing import Any

from futures_rollover_v1 import FuturesRolloverSummaryV1, resolve_saxo_futures_rollovers_once_v1
from saxo_provider import SaxoClient, SaxoInstrument, configured_client


LOGGER = logging.getLogger("pricegauger.futures_rollover_discovery_v2")
_FUTURES_ASSET_TYPES = frozenset({"ContractFutures", "CfdOnFutures"})


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _search_primary_listing_for_exact_uic_v2(
    client: SaxoClient,
    *,
    instrument: SaxoInstrument,
) -> int | None:
    """Rediscover PrimaryListing only through the exact stale UIC's Saxo summary.

    This deliberately does not choose a contract merely because its description looks
    similar. Saxo's reference-data search must return the exact current UIC, and that
    exact row must provide a distinct PrimaryListing. The normal rollover resolver then
    validates the target instrument's tradability and expiry before changing collection.
    """
    if str(instrument.asset_type) not in _FUTURES_ASSET_TYPES:
        return None
    keywords = str(instrument.asset or instrument.description or instrument.symbol or "").strip()
    if not keywords:
        return None
    payload = client._get(
        "ref/v1/instruments",
        params={
            "Keywords": keywords,
            "AssetTypes": str(instrument.asset_type),
            "$top": 100,
        },
    )
    rows = payload.get("Data") or []
    if not isinstance(rows, list):
        return None
    current_uic = int(instrument.uic)
    matches = [
        row
        for row in rows
        if isinstance(row, dict)
        and _positive_int(row.get("Identifier")) == current_uic
        and str(row.get("AssetType") or instrument.asset_type) == str(instrument.asset_type)
    ]
    if len(matches) != 1:
        return None
    primary = _positive_int(matches[0].get("PrimaryListing"))
    if primary is None or primary == current_uic:
        return None
    return primary


class _DiscoveryFallbackClientV2:
    """Read-only Saxo adapter that enriches stale futures details with broker evidence."""

    def __init__(self, client: SaxoClient) -> None:
        self._client = client

    def __getattr__(self, name: str):
        return getattr(self._client, name)

    def instrument_details(self, instrument: SaxoInstrument) -> dict[str, Any]:
        details = self._client.instrument_details(instrument)
        if not isinstance(details, dict):
            return details
        current_primary = _positive_int(details.get("PrimaryListing"))
        if current_primary is not None and current_primary != int(instrument.uic):
            return details
        try:
            discovered = _search_primary_listing_for_exact_uic_v2(
                self._client,
                instrument=instrument,
            )
        except Exception as exc:
            LOGGER.info(
                "Futures search fallback unavailable market=%s uic=%s: %s",
                instrument.asset,
                instrument.uic,
                exc,
            )
            return details
        if discovered is None:
            return details
        enriched = deepcopy(details)
        enriched["PrimaryListing"] = int(discovered)
        LOGGER.warning(
            "Futures rollover recovered broker PrimaryListing via exact-UIC search market=%s old_uic=%s next_uic=%s",
            instrument.asset,
            instrument.uic,
            discovered,
        )
        return enriched


def resolve_saxo_futures_rollovers_with_discovery_v2(
    *,
    client: SaxoClient | None = None,
    now: datetime | None = None,
    roll_lead_days: int = 5,
) -> FuturesRolloverSummaryV1:
    """Run the v1 atomic collection rollover with a broker-proven discovery fallback.

    The adapter enriches reference data only. The existing rollover implementation
    remains authoritative for due checks, immutable instrument creation, target
    tradability/expiry validation, atomic subscription switch and audit persistence.
    LIVE AutoManager/AutoTrader execution identity is never changed here.
    """
    sax = client or configured_client()
    if sax is None:
        return FuturesRolloverSummaryV1()
    return resolve_saxo_futures_rollovers_once_v1(
        client=_DiscoveryFallbackClientV2(sax),
        now=now,
        roll_lead_days=int(roll_lead_days),
    )


__all__ = [
    "resolve_saxo_futures_rollovers_with_discovery_v2",
]
