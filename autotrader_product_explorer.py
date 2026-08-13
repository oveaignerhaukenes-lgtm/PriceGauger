from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from saxo_provider import SaxoClient, SaxoError


DEFAULT_PRODUCT_SEARCH_LIMIT = 100
MAX_PRODUCT_SEARCH_LIMIT = 1000

# Common filters for humans investigating Saxo's instrument universe. "All" is
# represented by omitting AssetTypes entirely, so this list is not an allowlist.
COMMON_ASSET_TYPES: tuple[str, ...] = (
    "Warrant",
    "MiniFuture",
    "WarrantKnockOut",
    "WarrantOpenEndKnockOut",
    "WarrantOtherLeverageWithKnockOut",
    "WarrantDoubleKnockOut",
    "CfdOnFutures",
    "CfdOnIndex",
    "CfdOnStock",
    "ContractFutures",
    "Stock",
    "Etf",
    "Etn",
    "Etc",
    "FxSpot",
    "ContractOptions",
)


@dataclass(frozen=True, slots=True)
class SaxoProductSearch:
    keywords: str
    asset_type: str | None = None
    include_non_tradable: bool = False
    account_key: str | None = None
    limit: int = DEFAULT_PRODUCT_SEARCH_LIMIT

    def params(self) -> dict[str, Any]:
        keywords = self.keywords.strip()
        if not keywords:
            raise ValueError("Saxo Product Explorer krever søketekst")
        limit = int(self.limit)
        if limit < 1 or limit > MAX_PRODUCT_SEARCH_LIMIT:
            raise ValueError(f"limit må være mellom 1 og {MAX_PRODUCT_SEARCH_LIMIT}")

        params: dict[str, Any] = {
            "Keywords": keywords,
            "IncludeNonTradable": bool(self.include_non_tradable),
            "$top": limit,
        }
        asset_type = (self.asset_type or "").strip()
        if asset_type:
            params["AssetTypes"] = asset_type
        account_key = (self.account_key or "").strip()
        if account_key:
            params["AccountKey"] = account_key
        return params


@dataclass(frozen=True, slots=True)
class SaxoProductSummary:
    uic: int
    asset_type: str
    symbol: str
    description: str
    exchange_id: str | None
    exchange_name: str | None
    summary_type: str | None
    non_tradable_reason: str | None
    primary_listing: int | None
    underlying_asset_type: str | None
    tradable_as: tuple[str, ...]

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "SaxoProductSummary | None":
        identifier = value.get("Identifier")
        asset_type = value.get("AssetType")
        if identifier is None or not asset_type:
            return None
        try:
            uic = int(identifier)
        except (TypeError, ValueError):
            return None

        primary_listing_raw = value.get("PrimaryListing")
        try:
            primary_listing = int(primary_listing_raw) if primary_listing_raw is not None else None
        except (TypeError, ValueError):
            primary_listing = None

        tradable_as_raw = value.get("TradableAs")
        tradable_as = (
            tuple(str(item) for item in tradable_as_raw if item)
            if isinstance(tradable_as_raw, list)
            else ()
        )
        return cls(
            uic=uic,
            asset_type=str(asset_type),
            symbol=str(value.get("Symbol") or ""),
            description=str(value.get("Description") or ""),
            exchange_id=str(value.get("ExchangeId")) if value.get("ExchangeId") else None,
            exchange_name=str(value.get("ExchangeName")) if value.get("ExchangeName") else None,
            summary_type=str(value.get("SummaryType")) if value.get("SummaryType") else None,
            non_tradable_reason=(
                str(value.get("NonTradableReason")) if value.get("NonTradableReason") else None
            ),
            primary_listing=primary_listing,
            underlying_asset_type=(
                str(value.get("UnderlyingAssetType")) if value.get("UnderlyingAssetType") else None
            ),
            tradable_as=tradable_as,
        )

    def table_row(self) -> dict[str, Any]:
        return {
            "Description": self.description,
            "Symbol": self.symbol,
            "AssetType": self.asset_type,
            "UIC": self.uic,
            "Exchange": self.exchange_name or self.exchange_id or "",
            "NonTradableReason": self.non_tradable_reason or "",
            "TradableAs": ", ".join(self.tradable_as),
            "UnderlyingAssetType": self.underlying_asset_type or "",
        }


@dataclass(frozen=True, slots=True)
class SaxoProductSearchResult:
    search: SaxoProductSearch
    products: tuple[SaxoProductSummary, ...]
    raw_payload: dict[str, Any]

    @property
    def count(self) -> int:
        return len(self.products)

    @property
    def asset_type_counts(self) -> tuple[tuple[str, int], ...]:
        counts = Counter(product.asset_type for product in self.products)
        return tuple(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def search_saxo_products(client: SaxoClient, search: SaxoProductSearch) -> SaxoProductSearchResult:
    """Read Saxo's raw instrument-search universe without guessing or filtering results."""

    payload = client._get("ref/v1/instruments", params=search.params())
    raw_rows = payload.get("Data") or []
    if not isinstance(raw_rows, list):
        raise SaxoError("instrumentlisten hadde ugyldig format", status="INVALID_RESPONSE")

    products: list[SaxoProductSummary] = []
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        product = SaxoProductSummary.from_mapping(row)
        if product is not None:
            products.append(product)

    return SaxoProductSearchResult(
        search=search,
        products=tuple(products),
        raw_payload=payload,
    )
