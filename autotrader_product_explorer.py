from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from saxo_provider import SaxoClient, SaxoError, SaxoInstrument


ALL_CATEGORY = "Alle"
CATEGORY_ASSET_TYPES: dict[str, tuple[str, ...]] = {
    "Aksjer": ("Stock", "Rights", "IpoOnStock"),
    "ETF / ETC / ETN": ("Etf", "Etc", "Etn"),
    "CFD": (
        "CfdOnStock", "CfdOnEtf", "CfdOnEtc", "CfdOnEtn", "CfdOnFund",
        "CfdOnRights", "CfdOnIndex", "CfdOnFutures", "CfdIndexOption",
        "CfdOnCompanyWarrant",
    ),
    "Futures": ("ContractFutures", "FuturesStrategy"),
    "Opsjoner": (
        "FuturesOption", "StockOption", "StockIndexOption", "FxVanillaOption",
        "FxKnockInOption", "FxKnockOutOption", "FxOneTouchOption",
        "FxNoTouchOption", "FxBinaryOption",
    ),
    "Mini Futures": ("MiniFuture",),
    "Warrants / Turbo / KO": (
        "Warrant", "WarrantKnockOut", "WarrantOpenEndKnockOut",
        "WarrantOtherLeverageWithKnockOut", "WarrantOtherLeverageWithoutKnockOut",
        "WarrantDoubleKnockOut", "WarrantSpread", "InlineWarrant", "CompanyWarrant",
    ),
    "Certificates": (
        "CertificateBarrierDiscount", "CertificateBarrierReverseConvertibles",
        "CertificateBonus", "CertificateCapitalProtectionWithCoupon",
        "CertificateCapitalProtectionWithKnockOut", "CertificateCappedBonus",
        "CertificateCappedCapitalProtected", "CertificateCappedOutperformance",
        "CertificateConstantLeverage", "CertificateDiscount", "CertificateExpress",
        "CertificateOutperformanceBonus", "CertificateReverseConvertibles",
        "CertificateTracker", "CertificateUncappedCapitalProtection",
        "CertificateUncappedOutperformance", "SubscriptionOnCertificate",
        "CBBCCategoryN", "CBBCCategoryR",
    ),
    "Fond": ("Fund", "MutualFund"),
    "Valuta": ("FxSpot", "FxForwards", "FxSwap", "FxCrypto"),
    "Obligasjoner": ("Bond",),
    "Indekser": ("StockIndex",),
}
CATEGORY_OPTIONS = (ALL_CATEGORY, *CATEGORY_ASSET_TYPES.keys())
DIRECTION_OPTIONS = ("Alle", "Bull / Long", "Bear / Short", "Ukjent")

SAXO_PRODUCTS_URL = "https://www.home.saxo/nb-no/products"
SAXO_API_ASSET_TYPES_URL = (
    "https://www.developer.saxo/openapi/referencedocs/hist/v3/historicalpositions/"
    "get__hist_positions_clientkey/schema-assettype"
)
CATEGORY_EDUCATION_URLS: dict[str, str] = {
    "Aksjer": "https://www.home.saxo/nb-no/products/stocks",
    "ETF / ETC / ETN": "https://www.home.saxo/nb-no/products/etf",
    "CFD": "https://www.home.saxo/nb-no/products/cfds",
    "Futures": "https://www.home.saxo/nb-no/products/futures",
    "Opsjoner": "https://www.home.saxo/nb-no/products/listed-options",
    "Fond": "https://www.home.saxo/nb-no/products/mutual-funds",
    "Valuta": "https://www.home.saxo/nb-no/products/forex",
    "Obligasjoner": "https://www.home.saxo/nb-no/products/bonds",
}
CATEGORY_EXPLANATIONS: dict[str, str] = {
    "Aksjer": (
        "Direkte eierandel i et selskap. Vanlige aksjer har normalt ikke innebygd gearing "
        "eller knock-out, men kursen kan falle betydelig."
    ),
    "ETF / ETC / ETN": (
        "Børsnotert produkt som følger et marked, en kurv eller en strategi. ETF-er er fond, "
        "mens ETC/ETN kan ha annen juridisk struktur og utsteder-/kredittrisiko."
    ),
    "CFD": (
        "Derivat som følger prisendringen i et underliggende instrument uten at du eier det. "
        "CFD-er handles ofte på margin; gearing forsterker både gevinst og tap, og finansieringskostnader kan påløpe."
    ),
    "Futures": (
        "Standardisert derivatkontrakt med bestemt kontraktsstørrelse og normalt utløp. "
        "Margin gjør eksponeringen gearet, og kontrakts-/rollover-identitet er viktig."
    ),
    "Opsjoner": (
        "Derivat med ikke-lineær avkastning og utløp. Call/Put, strike, premie og tid til utløp "
        "bestemmer risikoen; kjøper og utsteder/selger har ulike risikoprofiler."
    ),
    "Mini Futures": (
        "Gearet strukturert produkt som normalt følger underliggende Long eller Short. "
        "Finansieringsnivå og stop-loss/knock-out er sentrale; treff på knock-out kan gi svært stort eller totalt tap."
    ),
    "Warrants / Turbo / KO": (
        "Strukturerte/gearede produkter med payoff som avhenger av type. Mange har Call/Put eller Long/Short, "
        "og noen har knock-out/barriere. Utløp, strike/barriere og utstederbetingelser må kontrolleres."
    ),
    "Certificates": (
        "Bred familie av strukturerte produkter. Payoff kan være tracker, constant leverage, bonus, discount, "
        "capital protection eller andre profiler. Les alltid de konkrete vilkårene; navnet alene er ikke nok."
    ),
    "Fond": (
        "Samleinvestering som eier en portefølje etter et mandat. Risiko, likviditet, kostnader og innløsningsvilkår varierer."
    ),
    "Valuta": (
        "Eksponering mot valutapar eller metall/valuta-kryss. Spot/forward/swap kan ha ulike oppgjørs- og finansieringsvilkår."
    ),
    "Obligasjoner": (
        "Gjeldsinstrument med rente- og kredittrisiko. Pris påvirkes blant annet av renter, kredittkvalitet og løpetid."
    ),
    "Indekser": (
        "Referanseindeks. Selve indeksen er ofte ikke et direkte tradable produkt; Saxos TradableAs-felt viser "
        "hvilke instrumenttyper samme markedsreferanse eventuelt kan handles som."
    ),
    "Andre": (
        "Saxo AssetType faller utenfor de menneskelige hovedkategoriene i Explorer. "
        "Bruk rå AssetType og Saxo-dokumentasjonen for å kontrollere produktets eksakte kontrakt."
    ),
}


@dataclass(frozen=True, slots=True)
class ProductSearchRequest:
    keywords: str
    category: str = ALL_CATEGORY
    direction: str = "Alle"
    include_non_tradable: bool = False
    account_key: str | None = None
    top: int = 100

    @property
    def asset_types(self) -> tuple[str, ...]:
        if self.category == ALL_CATEGORY:
            return ()
        return CATEGORY_ASSET_TYPES.get(self.category, ())


@dataclass(frozen=True, slots=True)
class ProductSummary:
    instrument: SaxoInstrument
    category: str
    direction: str
    currency: str | None
    exchange: str | None
    non_tradable_reason: str | None
    tradable_as: tuple[str, ...]
    underlying_asset_type: str | None
    raw: dict[str, Any]

    @property
    def is_tradable(self) -> bool:
        reason = (self.non_tradable_reason or "").strip()
        return not reason or reason.lower() == "none"


@dataclass(frozen=True, slots=True)
class ProductSearchResult:
    request: ProductSearchRequest
    products: tuple[ProductSummary, ...]
    raw_count: int


def category_for_asset_type(asset_type: str) -> str:
    for category, asset_types in CATEGORY_ASSET_TYPES.items():
        if asset_type in asset_types:
            return category
    return "Andre"


def direction_from_text(*values: str) -> str:
    text = " ".join(value for value in values if value).lower()
    if re.search(r"\b(bull|long|call)\b", text):
        return "Bull / Long"
    if re.search(r"\b(bear|short|put)\b", text):
        return "Bear / Short"
    return "Ukjent"


def _as_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value if item is not None)


def _instrument_from_summary(keywords: str, row: dict[str, Any]) -> SaxoInstrument | None:
    identifier = row.get("Identifier")
    asset_type = row.get("AssetType")
    if identifier is None or not asset_type:
        return None
    try:
        uic = int(identifier)
    except (TypeError, ValueError):
        return None
    return SaxoInstrument(
        asset=keywords,
        uic=uic,
        asset_type=str(asset_type),
        symbol=str(row.get("Symbol") or ""),
        description=str(row.get("Description") or ""),
        expiry=str(row.get("ExpiryDate")) if row.get("ExpiryDate") else None,
    )


def search_product_universe(client: SaxoClient, request: ProductSearchRequest) -> ProductSearchResult:
    keywords = request.keywords.strip()
    if not keywords:
        return ProductSearchResult(request=request, products=(), raw_count=0)

    top = min(max(int(request.top), 1), 250)
    params: dict[str, Any] = {
        "Keywords": keywords,
        "IncludeNonTradable": bool(request.include_non_tradable),
        "$top": top,
    }
    if request.asset_types:
        params["AssetTypes"] = ",".join(request.asset_types)
    if request.account_key:
        params["AccountKey"] = request.account_key

    payload = client._get("ref/v1/instruments", params=params)
    rows = payload.get("Data") or []
    if not isinstance(rows, list):
        raise SaxoError("instrumentlisten hadde ugyldig format", status="INVALID_RESPONSE")

    products: list[ProductSummary] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        instrument = _instrument_from_summary(keywords, row)
        if instrument is None:
            continue
        direction = direction_from_text(instrument.description, instrument.symbol)
        if request.direction != "Alle" and direction != request.direction:
            continue
        products.append(
            ProductSummary(
                instrument=instrument,
                category=category_for_asset_type(instrument.asset_type),
                direction=direction,
                currency=str(row.get("CurrencyCode") or "") or None,
                exchange=str(row.get("ExchangeName") or row.get("ExchangeId") or "") or None,
                non_tradable_reason=str(row.get("NonTradableReason") or "") or None,
                tradable_as=_as_tuple(row.get("TradableAs")),
                underlying_asset_type=str(row.get("UnderlyingAssetType") or "") or None,
                raw=dict(row),
            )
        )

    products.sort(
        key=lambda item: (
            0 if item.is_tradable else 1,
            item.category,
            item.direction,
            item.instrument.description.lower(),
            item.instrument.uic,
        )
    )
    return ProductSearchResult(request=request, products=tuple(products), raw_count=len(rows))


def load_product_details(
    client: SaxoClient,
    product: ProductSummary,
    *,
    account_key: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"FieldGroups": "OrderSetting"}
    if account_key:
        params["AccountKey"] = account_key
    return client._get(
        f"ref/v1/instruments/details/{product.instrument.uic}/{product.instrument.asset_type}",
        params=params,
    )


def product_explanation(product: ProductSummary) -> str:
    return CATEGORY_EXPLANATIONS.get(product.category, CATEGORY_EXPLANATIONS["Andre"])


def product_education_links(product: ProductSummary) -> tuple[tuple[str, str], ...]:
    links: list[tuple[str, str]] = []
    category_url = CATEGORY_EDUCATION_URLS.get(product.category)
    if category_url:
        links.append(("Saxo: om produkttypen", category_url))
    else:
        links.append(("Saxo: produktoversikt", SAXO_PRODUCTS_URL))
    links.append(("Saxo OpenAPI: AssetTypes", SAXO_API_ASSET_TYPES_URL))
    return tuple(links)


def detail_rows(details: dict[str, Any]) -> tuple[tuple[str, Any], ...]:
    exchange = details.get("Exchange") if isinstance(details.get("Exchange"), dict) else {}
    order_setting = details.get("OrderSetting") if isinstance(details.get("OrderSetting"), dict) else {}
    fields = (
        ("AssetType", details.get("AssetType")),
        ("UIC", details.get("Uic")),
        ("Symbol", details.get("Symbol")),
        ("Beskrivelse", details.get("Description")),
        ("Valuta", details.get("CurrencyCode") or details.get("PriceCurrency")),
        ("Børs", exchange.get("Name") or exchange.get("ExchangeId")),
        ("Tradable", details.get("IsTradable")),
        ("Ikke tradable fordi", details.get("NonTradableReason")),
        ("TradableAs", ", ".join(str(x) for x in details.get("TradableAs", [])) if isinstance(details.get("TradableAs"), list) else None),
        ("Utløp", details.get("ExpiryDate") or details.get("ExpiryDateTime")),
        ("Put/Call", details.get("PutCall")),
        ("Strike", details.get("StrikePrice")),
        ("Kontraktstørrelse", details.get("ContractSize")),
        ("Min. trade size", details.get("MinimumTradeSize")),
        ("Min. ordreverdi", details.get("MinimumOrderValue") or order_setting.get("MinOrderValue")),
        ("Default amount", details.get("DefaultAmount")),
        ("Increment size", details.get("IncrementSize")),
        ("Short disabled", details.get("ShortTradeDisabled")),
        ("Settlement", details.get("SettlementStyle")),
        ("Trading status", details.get("TradingStatus")),
    )
    return tuple((label, value) for label, value in fields if value not in (None, "", [], ()))
