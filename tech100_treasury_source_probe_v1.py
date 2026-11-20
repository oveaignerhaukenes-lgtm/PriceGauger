"""Manually triggered, GET-only Saxo US Treasury and yield-proxy diagnostics.

Never treats a future/CFD price as a 2/10/30Y par yield in basis points.
No subscription, storage mutation, order or background poll is performed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from saxo_provider import SaxoClient

TENOR_TERMS = {
    # Exact product-family wording observed in Saxo LIVE catalog on 2026-11-20.
    # These are MONTHLY yield FUTURES, not constant-maturity cash yields.
    "US2Y": "Micro 2-Year Yield",
    "US10Y": "Micro 10-Year Yield",
    "US30Y": "Micro 30-Year Yield",
}
# Saxo Bond is preferable if it actually exposes BidYield/AskYield. Otherwise
# explicitly-labelled market futures/CFDs may be tested as PRICE proxies only.
SEARCH_ASSET_TYPES = "Bond,ContractFutures,CfdOnFutures,CfdOnIndex,StockIndex"


@dataclass(frozen=True)
class TreasuryCandidate:
    tenor_hint: str
    uic: int
    asset_type: str
    symbol: str
    description: str
    expiry: str | None


@dataclass(frozen=True)
class TreasuryQuote:
    candidate: TreasuryCandidate
    observed_at: datetime
    source_updated_at: datetime | None
    delayed_by_minutes: float | None
    bid: float | None
    ask: float | None
    bid_yield_raw: float | None
    ask_yield_raw: float | None
    quote_error: str | None
    status: str
    detail: str


def _number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if isfinite(result) else None
    except (ValueError, TypeError):
        return None


def _timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            return parsed.astimezone(timezone.utc)
    except ValueError:
        pass
    return None


def search_treasury_candidates(
    client: SaxoClient, *, max_each: int = 60,
) -> dict[str, tuple[TreasuryCandidate, ...]]:
    """Three bounded existing catalog GETs, without selecting any product."""
    if not 1 <= max_each <= 100:
        raise ValueError("max_each must be 1..100")
    result = {}
    for tenor, term in TENOR_TERMS.items():
        payload = client._get(  # noqa: SLF001 - existing authenticated GET transport
            "ref/v1/instruments",
            params={"Keywords": term, "AssetTypes": SEARCH_ASSET_TYPES,
                    "IncludeNonTradable": True, "$top": max_each},
        )
        data = payload.get("Data") or []
        if not isinstance(data, list):
            raise ValueError(f"malformed Saxo instrument catalog for {tenor}")
        candidates = {}
        for row in data:
            if not isinstance(row, Mapping):
                continue
            try:
                uic = int(row["Identifier"])
            except (KeyError, TypeError, ValueError):
                continue
            kind = str(row.get("AssetType") or "")
            if uic <= 0 or kind not in SEARCH_ASSET_TYPES.split(","):
                continue
            description = str(row.get("Description") or "")
            # Saxo keyword queries can return unrelated symbol matches. Never
            # expose an unrelated Nasdaq/foreign contract as a US tenor source.
            if term.casefold() not in description.casefold():
                continue
            item = TreasuryCandidate(
                tenor_hint=tenor, uic=uic, asset_type=kind,
                symbol=str(row.get("Symbol") or ""),
                description=description,
                expiry=str(row["ExpiryDate"]) if row.get("ExpiryDate") else None,
            )
            candidates[(uic, kind)] = item
        result[tenor] = tuple(candidates.values())
    return result


def probe_treasury_quote(
    client: SaxoClient, candidate: TreasuryCandidate, *, at: datetime | None = None,
) -> TreasuryQuote:
    """Read the exact UIC's price and optional bid/ask yield, with age/delay."""
    now = at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("decision timestamp must include timezone")
    now = now.astimezone(timezone.utc)
    payload = client._get(  # noqa: SLF001 - GET only, never subscribes or orders
        "trade/v1/infoprices",
        params={"Uic": candidate.uic, "AssetType": candidate.asset_type,
                "FieldGroups": "PriceInfoDetails,Quote,InstrumentPriceDetails"},
    )
    quote = payload.get("Quote") or {}
    details = payload.get("PriceInfoDetails") or {}
    if not isinstance(quote, Mapping) or not isinstance(details, Mapping):
        raise ValueError("malformed Saxo quote")
    bid, ask = _number(quote.get("Bid")), _number(quote.get("Ask"))
    bid_yield, ask_yield = _number(details.get("BidYield")), _number(details.get("AskYield"))
    delayed = _number(quote.get("DelayedByMinutes"))
    source_updated = _timestamp(payload.get("LastUpdated"))
    error = str(quote.get("ErrorCode") or "None")

    if error not in ("None", "0"):
        state, reason = "QUOTE_ERROR", error
    elif delayed is None:
        state, reason = "DELAY_UNVERIFIED", "no observed DelayedByMinutes entitlement field"
    elif delayed > 0:
        state, reason = "DELAYED", f"Saxo reports {delayed:g} minute delay"
    elif source_updated is None:
        state, reason = "TIMESTAMP_UNVERIFIED", "missing LastUpdated timestamp"
    elif not -timedelta(seconds=5) <= now - source_updated <= timedelta(minutes=2):
        state, reason = "STALE", "quote LastUpdated older than 2m or in future"
    elif bid_yield is not None or ask_yield is not None:
        state, reason = "YIELD_OBSERVED", "instrument yield quoted; not an interpolated constant maturity"
    elif (bid is not None and bid > 0) or (ask is not None and ask > 0):
        state, reason = "PRICE_PROXY_ONLY", "price return requires separately calibrated yield sign/sensitivity"
    else:
        state, reason = "NO_PRICE", "no usable price or yield fields"
    return TreasuryQuote(candidate, now, source_updated, delayed, bid, ask,
                         bid_yield, ask_yield, error, state, reason)
