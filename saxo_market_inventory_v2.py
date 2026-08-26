from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable

from saxo_provider import SaxoClient


# Exact Saxo Index Tracker symbols documented on Saxo's CFD pricing pages. Keeping
# this as an aggregate discovery market lets PG compare a family of small,
# spread-priced CfdOnIndex instruments without assuming the user already knows
# which underlying market to trade.
INDEX_CFD_TRAINING_TERMS: tuple[str, ...] = (
    "US30.I",
    "US500.I",
    "USNAS100.I",
    "EU50.I",
    "FRA40.I",
    "GER40.I",
    "ITALY40.I",
    "NETH25.I",
    "SPAIN35.I",
    "SWE30.I",
    "SWISS20.I",
    "UK100.I",
    "AUS200.I",
    "HK50.I",
)


MARKET_INVENTORY_SEARCH_TERMS: dict[str, tuple[str, ...]] = {
    "Index CFDs · training": INDEX_CFD_TRAINING_TERMS,
    "Gold": ("Gold", "XAU", "XAUUSD", "Gold Spot"),
    "Silver": ("Silver", "XAG", "XAGUSD", "Silver Spot"),
    "Brent": ("Oil", "Brent", "Brent Crude", "Crude Oil", "ICE Brent", "UKOIL"),
    "Natural Gas": ("Natural Gas", "Nat Gas", "Henry Hub", "Gas"),
    "DXY": ("US Dollar Index", "Dollar Index", "DXY", "USDX"),
}

# Generic words such as "Gold" and "Oil" are useful for recall, but Saxo can return
# hundreds of unrelated names (Goldman Sachs, gold miners, oil companies, etc.).
# These precise aliases are therefore the first shortlist for market-linked products.
# Broad terms remain visible in a separate recall section; nothing is silently discarded.
MARKET_INVENTORY_PRECISE_TERMS: dict[str, tuple[str, ...]] = {
    "Index CFDs · training": INDEX_CFD_TRAINING_TERMS,
    "Gold": ("XAU", "XAUUSD", "Gold Spot"),
    "Silver": ("XAG", "XAGUSD", "Silver Spot"),
    "Brent": ("Brent", "Brent Crude", "ICE Brent", "UKOIL"),
    "Natural Gas": ("Natural Gas", "Nat Gas", "Henry Hub"),
    "DXY": ("US Dollar Index", "DXY", "USDX"),
}


@dataclass(frozen=True, slots=True)
class SaxoMarketInventoryAccountV2:
    account_key: str
    account_id: str
    currency: str

    @property
    def label(self) -> str:
        suffix = self.account_id[-4:] if self.account_id else "????"
        return f"…{suffix} {self.currency}".strip()


@dataclass(frozen=True, slots=True)
class SaxoMarketInventoryQueryV2:
    account_label: str
    query: str
    returned: int
    error: str | None = None


@dataclass(frozen=True, slots=True)
class SaxoMarketInventoryRowV2:
    account_label: str
    matched_queries: tuple[str, ...]
    identifier: int
    asset_type: str
    summary_type: str
    description: str
    symbol: str
    exchange_id: str | None
    exchange_name: str | None
    currency: str | None
    tradable_as: tuple[str, ...]
    underlying_asset_type: str | None
    non_tradable_reason: str | None
    group_id: int | None
    primary_listing: int | None

    @property
    def identity(self) -> tuple[int, str, str]:
        return (self.identifier, self.asset_type, self.summary_type)


@dataclass(frozen=True, slots=True)
class SaxoMarketInventoryResultV2:
    market: str
    rows: tuple[SaxoMarketInventoryRowV2, ...]
    queries: tuple[SaxoMarketInventoryQueryV2, ...]
    account_labels: tuple[str, ...]
    asset_type_counts: tuple[tuple[str, int], ...]

    @property
    def asset_type_count(self) -> int:
        return len(self.asset_type_counts)


def _integer(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _accounts(client: SaxoClient) -> tuple[SaxoMarketInventoryAccountV2, ...]:
    payload = client._get("port/v1/accounts/me")
    raw = payload.get("Data") or []
    if not isinstance(raw, list):
        return ()
    result: list[SaxoMarketInventoryAccountV2] = []
    for item in raw:
        if not isinstance(item, dict) or not item.get("AccountKey"):
            continue
        if item.get("Active") is False:
            continue
        result.append(
            SaxoMarketInventoryAccountV2(
                account_key=str(item["AccountKey"]),
                account_id=str(item.get("AccountId") or ""),
                currency=str(item.get("Currency") or ""),
            )
        )
    return tuple(result[:3])


def _search_all_asset_types(
    client: SaxoClient,
    *,
    account: SaxoMarketInventoryAccountV2 | None,
    keyword: str,
    top: int,
) -> list[dict[str, Any]]:
    # Deliberately NO AssetTypes filter here. This is the first-stage inventory:
    # ask Saxo what this account can see for the market, then classify afterwards.
    params: dict[str, Any] = {
        "Keywords": keyword,
        "IncludeNonTradable": True,
        "$top": min(max(int(top), 1), 250),
    }
    if account is not None:
        params["AccountKey"] = account.account_key
    payload = client._get("ref/v1/instruments", params=params)
    raw = payload.get("Data") or []
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def scan_saxo_market_inventory_v2(
    client: SaxoClient,
    *,
    market: str,
    max_per_query: int = 250,
) -> SaxoMarketInventoryResultV2:
    """List all account-visible Saxo search matches for a market before product filtering.

    This is intentionally product-agnostic and read-only. It does not infer suitability,
    costs, limited-loss status or execution eligibility. Its purpose is to establish the
    actual Saxo universe first, so later filters operate on observed products rather than
    guessed AssetTypes.
    """

    terms = MARKET_INVENTORY_SEARCH_TERMS.get(market, ())
    accounts = _accounts(client)
    scopes: tuple[SaxoMarketInventoryAccountV2 | None, ...] = accounts or (None,)
    query_results: list[SaxoMarketInventoryQueryV2] = []
    raw_by_identity: dict[tuple[int, str, str], dict[str, Any]] = {}
    queries_by_identity: dict[tuple[int, str, str], set[str]] = {}
    account_by_identity: dict[tuple[int, str, str], str] = {}

    for account in scopes:
        account_label = account.label if account is not None else "client-token"
        for term in terms:
            try:
                rows = _search_all_asset_types(
                    client,
                    account=account,
                    keyword=term,
                    top=max_per_query,
                )
                query_results.append(SaxoMarketInventoryQueryV2(account_label, term, len(rows)))
            except Exception as exc:
                query_results.append(
                    SaxoMarketInventoryQueryV2(
                        account_label,
                        term,
                        0,
                        f"{type(exc).__name__}: {exc}",
                    )
                )
                continue

            for item in rows:
                identifier = _integer(item.get("Identifier"))
                asset_type = str(item.get("AssetType") or "")
                summary_type = str(item.get("SummaryType") or "Instrument")
                if identifier is None or not asset_type:
                    continue
                identity = (identifier, asset_type, summary_type)
                raw_by_identity.setdefault(identity, item)
                queries_by_identity.setdefault(identity, set()).add(term)
                account_by_identity.setdefault(identity, account_label)

    inventory_rows: list[SaxoMarketInventoryRowV2] = []
    for identity, item in raw_by_identity.items():
        identifier, asset_type, summary_type = identity
        tradable_as_raw = item.get("TradableAs") or []
        tradable_as = tuple(str(value) for value in tradable_as_raw) if isinstance(tradable_as_raw, list) else ()
        inventory_rows.append(
            SaxoMarketInventoryRowV2(
                account_label=account_by_identity[identity],
                matched_queries=tuple(sorted(queries_by_identity.get(identity, set()))),
                identifier=identifier,
                asset_type=asset_type,
                summary_type=summary_type,
                description=str(item.get("Description") or ""),
                symbol=str(item.get("Symbol") or ""),
                exchange_id=str(item.get("ExchangeId") or "") or None,
                exchange_name=str(item.get("ExchangeName") or "") or None,
                currency=str(item.get("CurrencyCode") or "") or None,
                tradable_as=tradable_as,
                underlying_asset_type=str(item.get("UnderlyingAssetType") or "") or None,
                non_tradable_reason=str(item.get("NonTradableReason") or "") or None,
                group_id=_integer(item.get("GroupId")),
                primary_listing=_integer(item.get("PrimaryListing")),
            )
        )

    inventory_rows.sort(
        key=lambda item: (
            item.asset_type.lower(),
            item.description.lower(),
            item.symbol.lower(),
            item.identifier,
        )
    )
    counts = Counter(item.asset_type for item in inventory_rows)
    asset_type_counts = tuple(sorted(counts.items(), key=lambda pair: (-pair[1], pair[0].lower())))
    return SaxoMarketInventoryResultV2(
        market=market,
        rows=tuple(inventory_rows),
        queries=tuple(query_results),
        account_labels=tuple(account.label for account in accounts),
        asset_type_counts=asset_type_counts,
    )


def precise_market_rows_v2(result: SaxoMarketInventoryResultV2) -> tuple[SaxoMarketInventoryRowV2, ...]:
    precise_terms = set(MARKET_INVENTORY_PRECISE_TERMS.get(result.market, ()))
    if not precise_terms:
        return result.rows
    rows = [item for item in result.rows if precise_terms.intersection(item.matched_queries)]
    rows.sort(
        key=lambda item: (
            item.asset_type.lower(),
            item.description.lower(),
            item.symbol.lower(),
            item.identifier,
        )
    )
    return tuple(rows)


def broad_recall_rows_v2(result: SaxoMarketInventoryResultV2) -> tuple[SaxoMarketInventoryRowV2, ...]:
    precise_ids = {item.identity for item in precise_market_rows_v2(result)}
    return tuple(item for item in result.rows if item.identity not in precise_ids)


def market_inventory_rows_for_ui_v2(rows: Iterable[SaxoMarketInventoryRowV2]) -> list[dict[str, object]]:
    return [
        {
            "Produkt": item.description,
            "Symbol": item.symbol,
            "AssetType": item.asset_type,
            "SummaryType": item.summary_type,
            "Børs": item.exchange_name or item.exchange_id or "",
            "Valuta": item.currency or "",
            "TradableAs": ", ".join(item.tradable_as),
            "Underliggende type": item.underlying_asset_type or "",
            "Treff via": ", ".join(item.matched_queries),
            "UIC/ID": item.identifier,
            "Ikke tradable fordi": item.non_tradable_reason or "",
        }
        for item in rows
    ]


def asset_type_rows_for_ui_v2(result: SaxoMarketInventoryResultV2) -> list[dict[str, object]]:
    return [{"AssetType": name, "Treff": count} for name, count in result.asset_type_counts]


def precise_asset_type_rows_for_ui_v2(result: SaxoMarketInventoryResultV2) -> list[dict[str, object]]:
    counts = Counter(item.asset_type for item in precise_market_rows_v2(result))
    ordered = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0].lower()))
    return [{"AssetType": name, "Presise treff": count} for name, count in ordered]


def inventory_query_rows_for_ui_v2(queries: Iterable[SaxoMarketInventoryQueryV2]) -> list[dict[str, object]]:
    return [
        {
            "Konto": item.account_label,
            "Søk": item.query,
            "Treff uten produktfilter": item.returned,
            "Feil": item.error or "",
        }
        for item in queries
    ]
