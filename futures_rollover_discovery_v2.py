from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
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
    """Read Saxo's documented next-contract reference for this exact expired UIC.

    Normal keyword searches omit no-longer-tradable instruments; searching
    the *old* UIC with IncludeNonTradable=True is essential. Fallback keyword
    search is also non-tradable-aware and never guesses a candidate by name,
    ticker, expiry or position in search results. No broker mutations.
    """
    if str(instrument.asset_type) not in _FUTURES_ASSET_TYPES:
        return None
    current_uic = int(instrument.uic)
    keywords = str(instrument.asset or instrument.description or instrument.symbol or "").strip()
    requests = [
        {
            "Uics": str(current_uic),
            "AssetTypes": str(instrument.asset_type),
            "IncludeNonTradable": True,
            "$top": 25,
        },
    ]
    if keywords:
        requests.append(
            {
                "Keywords": keywords,
                "AssetTypes": str(instrument.asset_type),
                "IncludeNonTradable": True,
                "$top": 100,
            }
        )
    for params in requests:
        try:
            payload = client._get("ref/v1/instruments", params=params)
        except Exception as exc:
            LOGGER.info(
                "Saxo expired-futures summary read failed market=%s old_uic=%s mode=%s error_type=%s",
                instrument.asset,
                current_uic,
                "exact_uic" if "Uics" in params else "keyword",
                type(exc).__name__,
            )
            continue
        rows = payload.get("Data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            continue
        matches = [
            row
            for row in rows
            if isinstance(row, dict)
            and _positive_int(row.get("Identifier")) == current_uic
            and str(row.get("AssetType") or "") == str(instrument.asset_type)
        ]
        if len(matches) != 1:
            continue
        primary = _positive_int(matches[0].get("PrimaryListing"))
        if primary is not None and primary != current_uic:
            return primary
    return None

class _DiscoveryFallbackClientV2:
    """Read-only Saxo adapter that enriches stale futures details with broker evidence."""

    def __init__(self, client: SaxoClient, *, now: datetime | None = None, roll_lead_days: int = 5) -> None:
        self._client = client
        self._now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        self._lead_days = max(0, int(roll_lead_days))

    def __getattr__(self, name: str):
        return getattr(self._client, name)

    def instrument_details(self, instrument: SaxoInstrument) -> dict[str, Any]:
        details = self._client.instrument_details(instrument)
        if not isinstance(details, dict):
            return details
        current_primary = _positive_int(details.get("PrimaryListing"))
        if current_primary is not None and current_primary != int(instrument.uic):
            return details
        # Avoid a redundant ref GET for candidate contracts which are already
        # live and not near expiry. Expired/currently non-tradable contracts
        # still get an exact old-UIC broker lineage search.
        raw_expiry = details.get("ExpiryDateTime") or details.get("ExpiryDate")
        expiry = None
        if isinstance(raw_expiry, (datetime, str)):
            try:
                expiry = (
                    raw_expiry if isinstance(raw_expiry, datetime)
                    else datetime.fromisoformat(raw_expiry.replace("Z", "+00:00"))
                )
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)
                expiry = expiry.astimezone(timezone.utc)
            except (TypeError, ValueError, OverflowError):
                expiry = None
        due = (
            details.get("IsTradable") is False
            or (expiry is not None and
                expiry <= self._now + timedelta(days=self._lead_days))
        )
        if not due:
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
        client=_DiscoveryFallbackClientV2(
            sax, now=now, roll_lead_days=roll_lead_days,
        ),
        now=now,
        roll_lead_days=int(roll_lead_days),
    )


__all__ = [
    "resolve_saxo_futures_rollovers_with_discovery_v2",
]
