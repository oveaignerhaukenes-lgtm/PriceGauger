from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import logging
import re
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




_MONTH_CODE = "FGHJKMNQUVXZ"


def _futures_symbol_root_v3(raw: Any) -> str | None:
    """Extract an exact standardized futures root; never use fuzzy matching."""
    match = re.fullmatch(
        rf"([A-Z]{{1,6}})[{_MONTH_CODE}][0-9]{{1,2}}",
        str(raw or "").strip().upper(),
    )
    return match.group(1) if match else None


def _exchange_id_v3(details: dict[str, Any]) -> str:
    exchange = details.get("Exchange") or {}
    raw = exchange.get("ExchangeId") if isinstance(exchange, dict) else None
    return str(raw or details.get("ExchangeId") or "").strip().upper()


def _product_family_v3(value: Any) -> str:
    text = str(value or "").strip().casefold()
    # Saxo uses "Henry Hub Natural Gas - Sep 2026" for expiry contracts.
    return text.rsplit(" - ", 1)[0].strip()


def _same_family_successor_v3(
    client: SaxoClient,
    *,
    instrument: SaxoInstrument,
    old_details: dict[str, Any],
    rows: list,
    now: datetime,
) -> int | None:
    """Require multiple independent Saxo facts before recovering a missing old UIC.

    Broker search candidates alone confer NO collection authority. Verify old
    and successor UIC, instrument group, root, exchange, contract size,
    currency, product name family, expiry, and consensus PrimaryListing.
    Any missing/mismatched field means no substitution.
    """
    if str(instrument.asset_type) != "ContractFutures":
        return None
    old_root = _futures_symbol_root_v3(instrument.symbol)
    old_family = _product_family_v3(old_details.get("Description"))
    old_group = _positive_int(old_details.get("GroupId"))
    old_exchange = _exchange_id_v3(old_details)
    old_currency = str(old_details.get("CurrencyCode") or "").upper().strip()
    try:
        old_size = float(old_details.get("ContractSize"))
    except (ValueError, TypeError, OverflowError):
        return None
    if (
        not old_root or not old_group or not old_exchange or not old_currency
        or len(old_family) < 10 or old_size <= 0
        or _positive_int(old_details.get("Uic")) != int(instrument.uic)
        or str(old_details.get("AssetType") or "") != str(instrument.asset_type)
        or _futures_symbol_root_v3(old_details.get("Symbol")) != old_root
    ):
        return None
    same_named_family = [
        row for row in rows
        if isinstance(row, dict)
        and str(row.get("AssetType") or "") == str(instrument.asset_type)
        and _positive_int(row.get("Identifier")) not in (None, int(instrument.uic))
        and str(row.get("ExchangeId") or "").strip().upper() == old_exchange
        and _futures_symbol_root_v3(row.get("Symbol")) == old_root
        and _product_family_v3(row.get("Description")) == old_family
    ]
    # Any contradictory broker GroupId in the exact same family means
    # this is not a uniquely proven continuous futures series.
    if any(_positive_int(row.get("GroupId")) != old_group for row in same_named_family):
        return None
    relatives = same_named_family
    if len(relatives) < 2:
        return None
    primaries = {_positive_int(row.get("PrimaryListing")) for row in relatives}
    if len(primaries) != 1:
        return None
    chosen = next(iter(primaries))
    if not chosen or chosen == int(instrument.uic):
        return None
    matching = [row for row in relatives if _positive_int(row.get("Identifier")) == chosen]
    if len(matching) != 1:
        return None
    try:
        new_details = client.instrument_details(
            SaxoInstrument(
                asset=instrument.asset, uic=chosen,
                asset_type=str(instrument.asset_type),
            )
        )
        if not isinstance(new_details, dict):
            return None
        new_size = float(new_details.get("ContractSize"))
        expiry_raw = new_details.get("ExpiryDateTime") or new_details.get("ExpiryDate")
        expiry = datetime.fromisoformat(str(expiry_raw).replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        expiry = expiry.astimezone(timezone.utc)
        now_utc = now.astimezone(timezone.utc)
    except Exception:
        return None
    if not (
        _positive_int(new_details.get("Uic")) == chosen
        and str(new_details.get("AssetType") or "") == str(instrument.asset_type)
        and new_details.get("IsTradable") is True
        and expiry > now_utc + timedelta(days=1)
        and _positive_int(new_details.get("GroupId")) == old_group
        and _exchange_id_v3(new_details) == old_exchange
        and str(new_details.get("CurrencyCode") or "").upper().strip() == old_currency
        and _futures_symbol_root_v3(new_details.get("Symbol")) == old_root
        and _product_family_v3(new_details.get("Description")) == old_family
        and abs(new_size - old_size) <= max(1e-8, abs(old_size) * 1e-10)
    ):
        return None
    LOGGER.warning(
        "Saxo futures family VERIFIED old_uic=%s new_uic=%s "
        "root=%s group=%s exchange=%s currency=%s "
        "candidate_count=%s (collection-data only)",
        instrument.uic, chosen, old_root, old_group, old_exchange,
        old_currency, len(relatives),
    )
    return chosen


def _search_primary_listing_for_exact_uic_v2(
    client: SaxoClient,
    *,
    instrument: SaxoInstrument,
    current_details: dict[str, Any] | None = None,
    now: datetime | None = None,
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
            if "Keywords" in params and not matches and current_details is not None:
                verified = _same_family_successor_v3(
                    client, instrument=instrument, old_details=current_details,
                    rows=rows, now=now or datetime.now(timezone.utc),
                )
                if verified is not None:
                    return verified
            if "Keywords" in params and not matches:
                # Public Saxo contract summaries for operator investigation.
                # Not an authority to switch the collection subscription.
                # Cap and sanitize output; no account ID or broker tokens.
                def safe(value: Any, length: int = 70) -> str:
                    return "".join(
                        c for c in str(value or "")[:length]
                        if c.isprintable()
                    )
                entries = [
                    {
                        "uic": _positive_int(row.get("Identifier")),
                        "symbol": safe(row.get("Symbol"), 32),
                        "description": safe(row.get("Description")),
                        "exchange": safe(row.get("ExchangeId"), 24),
                        "display_hint": safe(row.get("DisplayHint"), 24),
                        "primary": _positive_int(row.get("PrimaryListing")),
                    }
                    for row in rows
                    if isinstance(row, dict)
                    and str(row.get("AssetType") or "") == str(instrument.asset_type)
                    and _positive_int(row.get("Identifier")) is not None
                ]
                LOGGER.warning(
                    "Saxo expired-futures lineage UNRESOLVED market=%s old_uic=%s "
                    "asset_type=%s broker_candidate_count=%d first_candidates=%s "
                    "(READ_ONLY; no substitution)",
                    safe(instrument.asset),
                    current_uic,
                    safe(instrument.asset_type),
                    len(entries),
                    entries[:12],
                )
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
                current_details=details,
                now=self._now,
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
            "Futures rollover recovered broker-verified PrimaryListing market=%s old_uic=%s next_uic=%s",
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
