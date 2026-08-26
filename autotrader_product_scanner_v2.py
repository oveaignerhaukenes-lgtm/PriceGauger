from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable
from urllib.parse import quote

from autotrader_product_universe_v2 import evaluate_product_eligibility_v2
from saxo_provider import SaxoClient, SaxoInstrument
from trading_desk_products import LeveragedProduct, LeveragedProductDetails, product_details


# Discovery is intentionally broader than the execution universe. These are only
# read-only candidates; PG still fails closed unless an exact identity is curated.
SCANNER_STRUCTURED_ASSET_TYPES: tuple[str, ...] = (
    "MiniFuture",
    "Warrant",
    "WarrantKnockOut",
    "WarrantOpenEndKnockOut",
    "WarrantOtherLeverageWithKnockOut",
    "WarrantOtherLeverageWithoutKnockOut",
    "WarrantDoubleKnockOut",
    "CertificateConstantLeverage",
)
SCANNER_ASSET_TYPES = ",".join(SCANNER_STRUCTURED_ASSET_TYPES)

# Saxo documents that keyword search uses symbol, description and internal aliases
# (for example "Oil"). Keep aliases explicit/versioned so a zero-result scan is
# diagnosable instead of silently treated as "Saxo has no products".
SCANNER_MARKET_SEARCH_TERMS: dict[str, tuple[str, ...]] = {
    "Gold": ("Gold", "XAU", "XAUUSD", "Gold Spot"),
    "Silver": ("Silver", "XAG", "XAGUSD", "Silver Spot"),
    "Brent": ("Oil", "Brent", "Brent Crude", "Crude Oil", "ICE Brent", "UKOIL"),
    "Natural Gas": ("Natural Gas", "Nat Gas", "Henry Hub", "Gas"),
    "DXY": ("US Dollar Index", "Dollar Index", "DXY", "USDX"),
}


@dataclass(frozen=True, slots=True)
class SaxoScannerAccountV2:
    account_key: str
    account_id: str
    currency: str

    @property
    def label(self) -> str:
        suffix = self.account_id[-4:] if self.account_id else "????"
        return f"…{suffix} {self.currency}".strip()


@dataclass(frozen=True, slots=True)
class ProductSearchDiagnosticV2:
    account_label: str
    query: str
    exchange_id: str | None
    count: int
    error: str | None = None


@dataclass(frozen=True, slots=True)
class _DiscoveredCandidateV2:
    product: LeveragedProduct
    account: SaxoScannerAccountV2 | None
    exchange_id: str | None
    exchange_name: str | None


@dataclass(frozen=True, slots=True)
class ProductScanRowV2:
    market: str
    uic: int
    asset_type: str
    description: str
    direction: str | None
    currency: str | None
    exchange: str | None
    is_tradable: bool | None
    bid: float | None
    ask: float | None
    mid: float | None
    spread_pct: float | None
    minimum_trade_size: float | None
    minimum_trade_value: float | None
    increment_size: float | None
    barrier: float | None
    financing_level: float | None
    commission_cost: float | None
    commission_currency: str | None
    zero_commission: bool | None
    total_cost_pct: float | None
    cost_assumptions: tuple[str, ...]
    cost_error: str | None
    in_pg_universe: bool
    pg_eligible: bool
    eligibility_reasons: tuple[str, ...]
    scan_error: str | None = None

    @property
    def identity(self) -> tuple[int, str]:
        return (self.uic, self.asset_type)


@dataclass(frozen=True, slots=True)
class ProductScanResultV2:
    market: str
    rows: tuple[ProductScanRowV2, ...]
    discovered: int
    inspected: int
    failed: int
    account_labels: tuple[str, ...] = ()
    structured_universe_count: int | None = None
    cats_universe_count: int | None = None
    diagnostics: tuple[ProductSearchDiagnosticV2, ...] = ()


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _number_or_zero(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _quote_fields(payload: dict) -> tuple[float | None, float | None, float | None, float | None]:
    quote_data = payload.get("Quote") if isinstance(payload.get("Quote"), dict) else {}
    bid = _number(quote_data.get("Bid"))
    ask = _number(quote_data.get("Ask"))
    mid = _number(quote_data.get("Mid"))
    if mid is None and bid is not None and ask is not None:
        mid = (bid + ask) / 2.0
    spread_pct = None
    if bid is not None and ask is not None and mid is not None and mid > 0:
        spread_pct = (ask - bid) / mid
    return bid, ask, mid, spread_pct


def _direction_from_text(*values: str) -> str | None:
    text = " ".join(value for value in values if value).lower()
    if re.search(r"\b(long|bull|call)\b", text):
        return "Long"
    if re.search(r"\b(short|bear|put)\b", text):
        return "Short"
    return None


def _scanner_accounts(client: SaxoClient) -> tuple[SaxoScannerAccountV2, ...]:
    payload = client._get("port/v1/accounts/me")
    rows = payload.get("Data") or []
    if not isinstance(rows, list):
        return ()
    result: list[SaxoScannerAccountV2] = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("AccountKey"):
            continue
        if row.get("Active") is False:
            continue
        result.append(
            SaxoScannerAccountV2(
                account_key=str(row["AccountKey"]),
                account_id=str(row.get("AccountId") or ""),
                currency=str(row.get("Currency") or ""),
            )
        )
    return tuple(result[:3])


def _search_payload(
    client: SaxoClient,
    *,
    account: SaxoScannerAccountV2 | None,
    keyword: str | None,
    exchange_id: str | None = None,
    top: int = 250,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "AssetTypes": SCANNER_ASSET_TYPES,
        "IncludeNonTradable": True,
        "$top": min(max(int(top), 1), 250),
    }
    if account is not None:
        params["AccountKey"] = account.account_key
    if keyword:
        params["Keywords"] = keyword
    if exchange_id:
        params["ExchangeId"] = exchange_id
    return client._get("ref/v1/instruments", params=params)


def _payload_count(payload: dict[str, Any]) -> int:
    raw = payload.get("Data") or []
    returned = len(raw) if isinstance(raw, list) else 0
    try:
        total = int(payload.get("__count"))
    except (TypeError, ValueError):
        total = returned
    return max(returned, total)


def _instrument_from_summary(market: str, row: dict[str, Any]) -> SaxoInstrument | None:
    identifier = row.get("Identifier")
    asset_type = row.get("AssetType")
    if identifier is None or not asset_type:
        return None
    try:
        uic = int(identifier)
    except (TypeError, ValueError):
        return None
    return SaxoInstrument(
        asset=market,
        uic=uic,
        asset_type=str(asset_type),
        symbol=str(row.get("Symbol") or ""),
        description=str(row.get("Description") or ""),
        expiry=str(row.get("ExpiryDate")) if row.get("ExpiryDate") else None,
    )


def _discover_candidates_v2(
    client: SaxoClient,
    *,
    market: str,
) -> tuple[
    tuple[_DiscoveredCandidateV2, ...],
    tuple[SaxoScannerAccountV2, ...],
    tuple[ProductSearchDiagnosticV2, ...],
    int | None,
    int | None,
]:
    terms = SCANNER_MARKET_SEARCH_TERMS.get(market, ())
    accounts = _scanner_accounts(client)
    scopes: tuple[SaxoScannerAccountV2 | None, ...] = accounts or (None,)
    diagnostics: list[ProductSearchDiagnosticV2] = []
    by_identity: dict[tuple[int, str], _DiscoveredCandidateV2] = {}
    structured_count = 0
    cats_count = 0
    structured_probe_ok = False
    cats_probe_ok = False

    for account in scopes:
        account_label = account.label if account is not None else "client-token"
        try:
            broad = _search_payload(client, account=account, keyword=None, top=1)
            count = _payload_count(broad)
            structured_count = max(structured_count, count)
            structured_probe_ok = True
            diagnostics.append(ProductSearchDiagnosticV2(account_label, "<all structured>", None, count))
        except Exception as exc:
            diagnostics.append(
                ProductSearchDiagnosticV2(
                    account_label,
                    "<all structured>",
                    None,
                    0,
                    f"{type(exc).__name__}: {exc}",
                )
            )

        try:
            cats = _search_payload(client, account=account, keyword=None, exchange_id="CATS", top=1)
            count = _payload_count(cats)
            cats_count = max(cats_count, count)
            cats_probe_ok = True
            diagnostics.append(ProductSearchDiagnosticV2(account_label, "<all structured>", "CATS", count))
        except Exception as exc:
            diagnostics.append(
                ProductSearchDiagnosticV2(
                    account_label,
                    "<all structured>",
                    "CATS",
                    0,
                    f"{type(exc).__name__}: {exc}",
                )
            )

        for keyword in terms:
            try:
                payload = _search_payload(client, account=account, keyword=keyword)
                rows = payload.get("Data") or []
                if not isinstance(rows, list):
                    rows = []
                diagnostics.append(ProductSearchDiagnosticV2(account_label, keyword, None, len(rows)))
            except Exception as exc:
                diagnostics.append(
                    ProductSearchDiagnosticV2(
                        account_label,
                        keyword,
                        None,
                        0,
                        f"{type(exc).__name__}: {exc}",
                    )
                )
                continue

            for raw in rows:
                if not isinstance(raw, dict):
                    continue
                instrument = _instrument_from_summary(market, raw)
                if instrument is None or instrument.asset_type not in SCANNER_STRUCTURED_ASSET_TYPES:
                    continue
                identity = (instrument.uic, instrument.asset_type)
                if identity in by_identity:
                    continue
                product = LeveragedProduct(
                    instrument=instrument,
                    direction=_direction_from_text(instrument.description, instrument.symbol),
                )
                by_identity[identity] = _DiscoveredCandidateV2(
                    product=product,
                    account=account,
                    exchange_id=str(raw.get("ExchangeId") or "") or None,
                    exchange_name=str(raw.get("ExchangeName") or "") or None,
                )

    candidates = list(by_identity.values())
    candidates.sort(
        key=lambda item: (
            0 if (item.exchange_id or "").upper() == "CATS" else 1,
            {"Long": 0, "Short": 1, None: 2}.get(item.product.direction, 2),
            item.product.instrument.description.lower(),
            item.product.instrument.uic,
        )
    )
    return (
        tuple(candidates),
        accounts,
        tuple(diagnostics),
        structured_count if structured_probe_ok else None,
        cats_count if cats_probe_ok else None,
    )


def _sum_commissions(trading_cost: dict[str, Any]) -> float | None:
    if not isinstance(trading_cost, dict):
        return None
    commissions = trading_cost.get("Commissions")
    if commissions is None:
        # A successful cost illustration with no Commissions component means Saxo
        # did not apply an explicit brokerage commission in the illustration.
        return 0.0
    if not isinstance(commissions, list):
        return None
    total = 0.0
    for item in commissions:
        if not isinstance(item, dict):
            continue
        value = _number_or_zero(item.get("Value"))
        if value is not None:
            total += value
    return total


def _cost_illustration_v2(
    client: SaxoClient,
    *,
    account: SaxoScannerAccountV2 | None,
    product: LeveragedProduct,
    details: LeveragedProductDetails,
    price: float | None,
) -> tuple[float | None, str | None, bool | None, float | None, tuple[str, ...], str | None]:
    if account is None:
        return None, None, None, None, (), "AccountKey unavailable"
    if price is None or price <= 0:
        return None, None, None, None, (), "Price unavailable for cost illustration"

    amount = details.minimum_trade_size or details.increment_size or details.default_amount or 1.0
    if amount <= 0:
        amount = 1.0
    instrument = product.instrument
    path = (
        f"cs/v1/tradingconditions/cost/{quote(account.account_key, safe='')}/"
        f"{instrument.uic}/{instrument.asset_type}"
    )
    try:
        payload = client._get(
            path,
            params={
                "Amount": amount,
                "ApplyCostsZeroFloor": False,
                "HoldingPeriodInDays": 1,
                "Price": price,
                "TradeContext": "ClientTrading",
            },
        )
    except Exception as exc:
        return None, None, None, None, (), f"{type(exc).__name__}: {exc}"

    cost = payload.get("Cost") if isinstance(payload.get("Cost"), dict) else {}
    # Buying a short-underlying turbo is still a long position in the security itself.
    side = cost.get("Long") if isinstance(cost.get("Long"), dict) else {}
    trading_cost = side.get("TradingCost") if isinstance(side.get("TradingCost"), dict) else {}
    commission = _sum_commissions(trading_cost)
    currency = str(side.get("Currency") or payload.get("AccountCurrency") or "") or None
    total_cost_pct = _number_or_zero(side.get("TotalCostPct"))
    assumptions_raw = payload.get("CostCalculationAssumptions") or []
    assumptions = tuple(str(item) for item in assumptions_raw) if isinstance(assumptions_raw, list) else ()
    zero_commission = None if commission is None else abs(commission) <= 1e-12
    return commission, currency, zero_commission, total_cost_pct, assumptions, None


def _row(
    *,
    market: str,
    candidate: _DiscoveredCandidateV2,
    details: LeveragedProductDetails | None,
    info_price: dict | None,
    cost_data: tuple[float | None, str | None, bool | None, float | None, tuple[str, ...], str | None] | None,
    error: str | None = None,
) -> ProductScanRowV2:
    product = candidate.product
    eligibility = evaluate_product_eligibility_v2(market=market, product=product, details=details)
    bid = ask = mid = spread_pct = None
    if info_price is not None:
        bid, ask, mid, spread_pct = _quote_fields(info_price)
    instrument = product.instrument
    minimum_trade_size = details.minimum_trade_size if details is not None else None
    minimum_trade_value = None
    if ask is not None and minimum_trade_size is not None:
        minimum_trade_value = ask * minimum_trade_size
    commission_cost = commission_currency = zero_commission = total_cost_pct = cost_error = None
    cost_assumptions: tuple[str, ...] = ()
    if cost_data is not None:
        commission_cost, commission_currency, zero_commission, total_cost_pct, cost_assumptions, cost_error = cost_data
    return ProductScanRowV2(
        market=market,
        uic=int(instrument.uic),
        asset_type=str(instrument.asset_type),
        description=instrument.description or instrument.symbol or f"UIC {instrument.uic}",
        direction=(details.direction if details is not None else product.direction),
        currency=(details.currency if details is not None else None),
        exchange=candidate.exchange_name or candidate.exchange_id,
        is_tradable=(details.is_tradable if details is not None else None),
        bid=bid,
        ask=ask,
        mid=mid,
        spread_pct=spread_pct,
        minimum_trade_size=minimum_trade_size,
        minimum_trade_value=minimum_trade_value,
        increment_size=(details.increment_size if details is not None else None),
        barrier=(details.barrier if details is not None else None),
        financing_level=(details.financing_level if details is not None else None),
        commission_cost=commission_cost,
        commission_currency=commission_currency,
        zero_commission=zero_commission,
        total_cost_pct=total_cost_pct,
        cost_assumptions=cost_assumptions,
        cost_error=cost_error,
        in_pg_universe=eligibility.entry is not None,
        pg_eligible=eligibility.eligible,
        eligibility_reasons=eligibility.reasons,
        scan_error=error,
    )


def scan_saxo_candidates_v2(
    client: SaxoClient,
    *,
    market: str,
    max_products: int = 20,
) -> ProductScanResultV2:
    """Search the user's Saxo-visible structured universe and inspect costs read-only.

    Discovery is account-aware and deliberately broader than execution eligibility.
    The scanner may identify zero-commission candidates from Saxo's own cost model,
    but it never promotes a product into PG's allowlist and never infers limited-loss
    or no-margin safety from the product name or AssetType alone.
    """

    discovered, accounts, diagnostics, structured_count, cats_count = _discover_candidates_v2(
        client,
        market=market,
    )
    candidates = tuple(discovered[: max(1, int(max_products))])
    rows: list[ProductScanRowV2] = []
    failed = 0
    for candidate in candidates:
        product = candidate.product
        try:
            details = product_details(client, product)
            info = client.info_price(product.instrument)
            bid, ask, mid, _spread = _quote_fields(info)
            price = ask or mid or bid
            cost_data = _cost_illustration_v2(
                client,
                account=candidate.account,
                product=product,
                details=details,
                price=price,
            )
            rows.append(
                _row(
                    market=market,
                    candidate=candidate,
                    details=details,
                    info_price=info,
                    cost_data=cost_data,
                )
            )
        except Exception as exc:
            failed += 1
            rows.append(
                _row(
                    market=market,
                    candidate=candidate,
                    details=None,
                    info_price=None,
                    cost_data=None,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )

    rows.sort(
        key=lambda item: (
            0 if item.zero_commission is True else 1,
            0 if item.pg_eligible else 1,
            0 if item.is_tradable else 1,
            float("inf") if item.spread_pct is None else item.spread_pct,
            item.description.lower(),
            item.uic,
        )
    )
    return ProductScanResultV2(
        market=market,
        rows=tuple(rows),
        discovered=len(discovered),
        inspected=len(candidates),
        failed=failed,
        account_labels=tuple(account.label for account in accounts),
        structured_universe_count=structured_count,
        cats_universe_count=cats_count,
        diagnostics=diagnostics,
    )


def candidate_rows_for_ui_v2(rows: Iterable[ProductScanRowV2]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for item in rows:
        result.append(
            {
                "Produkt": item.description,
                "Retning": item.direction or "?",
                "AssetType": item.asset_type,
                "Børs": item.exchange or "",
                "UIC": item.uic,
                "Valuta": item.currency or "",
                "Bid": item.bid,
                "Ask": item.ask,
                "Spread %": None if item.spread_pct is None else item.spread_pct * 100.0,
                "Min. størrelse": item.minimum_trade_size,
                "Ca. min. verdi": item.minimum_trade_value,
                "Steg": item.increment_size,
                "Kommisjon*": item.commission_cost,
                "Komm. valuta": item.commission_currency or "",
                "0 kommisjon*": item.zero_commission,
                "Total kost %*": item.total_cost_pct,
                "Barrier": item.barrier,
                "Finansiering": item.financing_level,
                "Tradable": item.is_tradable,
                "I PG-univers": item.in_pg_universe,
                "AutoTrader eligible": item.pg_eligible,
                "Blokkert fordi": ", ".join(item.eligibility_reasons),
                "Kost-feil": item.cost_error or "",
                "Scan-feil": item.scan_error or "",
            }
        )
    return result


def diagnostic_rows_for_ui_v2(diagnostics: Iterable[ProductSearchDiagnosticV2]) -> list[dict[str, object]]:
    return [
        {
            "Konto": item.account_label,
            "Søk": item.query,
            "Børsfilter": item.exchange_id or "",
            "Treff": item.count,
            "Feil": item.error or "",
        }
        for item in diagnostics
    ]
