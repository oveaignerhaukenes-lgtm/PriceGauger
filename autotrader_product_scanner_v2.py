from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from autotrader_product_sizing import quote_price
from autotrader_product_universe_v2 import evaluate_product_eligibility_v2
from saxo_provider import SaxoClient
from trading_desk_products import LeveragedProduct, LeveragedProductDetails, discover_leveraged_products, product_details


@dataclass(frozen=True, slots=True)
class ProductScanRowV2:
    market: str
    uic: int
    asset_type: str
    description: str
    direction: str | None
    currency: str | None
    is_tradable: bool | None
    bid: float | None
    ask: float | None
    mid: float | None
    spread_pct: float | None
    minimum_trade_size: float | None
    increment_size: float | None
    barrier: float | None
    financing_level: float | None
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


def _number(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _quote_fields(payload: dict) -> tuple[float | None, float | None, float | None, float | None]:
    quote = payload.get("Quote") if isinstance(payload.get("Quote"), dict) else {}
    bid = _number(quote.get("Bid"))
    ask = _number(quote.get("Ask"))
    mid = _number(quote.get("Mid"))
    if mid is None and bid is not None and ask is not None:
        mid = (bid + ask) / 2.0
    spread_pct = None
    if bid is not None and ask is not None and mid is not None and mid > 0:
        spread_pct = (ask - bid) / mid
    return bid, ask, mid, spread_pct


def _row(
    *,
    market: str,
    product: LeveragedProduct,
    details: LeveragedProductDetails | None,
    info_price: dict | None,
    error: str | None = None,
) -> ProductScanRowV2:
    eligibility = evaluate_product_eligibility_v2(
        market=market,
        product=product,
        details=details,
    )
    bid = ask = mid = spread_pct = None
    if info_price is not None:
        bid, ask, mid, spread_pct = _quote_fields(info_price)
    instrument = product.instrument
    return ProductScanRowV2(
        market=market,
        uic=int(instrument.uic),
        asset_type=str(instrument.asset_type),
        description=instrument.description or instrument.symbol or f"UIC {instrument.uic}",
        direction=(details.direction if details is not None else product.direction),
        currency=(details.currency if details is not None else None),
        is_tradable=(details.is_tradable if details is not None else None),
        bid=bid,
        ask=ask,
        mid=mid,
        spread_pct=spread_pct,
        minimum_trade_size=(details.minimum_trade_size if details is not None else None),
        increment_size=(details.increment_size if details is not None else None),
        barrier=(details.barrier if details is not None else None),
        financing_level=(details.financing_level if details is not None else None),
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
    """Inspect a bounded subset of Saxo leveraged-product candidates.

    This is discovery/diagnostics only. The scanner never promotes a Saxo result into
    the AutoTrader product universe and never infers limited-loss or no-margin status.
    Exact execution eligibility remains owned by the PG allowlist.
    """

    discovered = discover_leveraged_products(client, market)
    candidates = tuple(discovered[: max(1, int(max_products))])
    rows: list[ProductScanRowV2] = []
    failed = 0
    for product in candidates:
        try:
            details = product_details(client, product)
            info = client.info_price(product.instrument)
            rows.append(_row(market=market, product=product, details=details, info_price=info))
        except Exception as exc:
            failed += 1
            rows.append(
                _row(
                    market=market,
                    product=product,
                    details=None,
                    info_price=None,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )

    rows.sort(
        key=lambda item: (
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
    )


def candidate_rows_for_ui_v2(rows: Iterable[ProductScanRowV2]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for item in rows:
        result.append(
            {
                "Produkt": item.description,
                "Retning": item.direction or "?",
                "AssetType": item.asset_type,
                "UIC": item.uic,
                "Valuta": item.currency or "",
                "Bid": item.bid,
                "Ask": item.ask,
                "Spread %": None if item.spread_pct is None else item.spread_pct * 100.0,
                "Min. størrelse": item.minimum_trade_size,
                "Steg": item.increment_size,
                "Barrier": item.barrier,
                "Finansiering": item.financing_level,
                "Tradable": item.is_tradable,
                "I PG-univers": item.in_pg_universe,
                "AutoTrader eligible": item.pg_eligible,
                "Blokkert fordi": ", ".join(item.eligibility_reasons),
                "Scan-feil": item.scan_error or "",
            }
        )
    return result
