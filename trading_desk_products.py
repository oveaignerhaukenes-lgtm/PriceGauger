from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from saxo_provider import SaxoClient, SaxoInstrument


LEVERAGED_ASSET_TYPE_NAMES = (
    "MiniFuture",
    "WarrantKnockOut",
    "WarrantOpenEndKnockOut",
    "WarrantOtherLeverageWithKnockOut",
    "WarrantDoubleKnockOut",
)
LEVERAGED_ASSET_TYPES = ",".join(LEVERAGED_ASSET_TYPE_NAMES)
MARKET_SEARCH_TERMS: dict[str, tuple[str, ...]] = {
    "Gold": ("Gold", "XAU", "XAUUSD"),
    "Silver": ("Silver", "XAG", "XAGUSD"),
    "Brent": ("Brent", "Brent Crude", "ICE Brent"),
    "Natural Gas": ("Natural Gas", "Nat Gas", "Henry Hub"),
    "DXY": ("US Dollar Index", "Dollar Index", "DXY"),
}


@dataclass(frozen=True, slots=True)
class LeveragedProduct:
    instrument: SaxoInstrument
    direction: str | None = None


@dataclass(frozen=True, slots=True)
class LeveragedProductDetails:
    instrument: SaxoInstrument
    direction: str | None
    is_tradable: bool | None
    currency: str | None
    barrier: float | None
    financing_level: float | None
    strike: float | None
    default_amount: float | None
    minimum_trade_size: float | None = None
    minimum_order_value: float | None = None
    increment_size: float | None = None
    amount_decimals: int | None = None


def _direction_from_text(*values: str) -> str | None:
    text = " ".join(value for value in values if value).lower()
    if re.search(r"\b(long|bull)\b", text):
        return "Long"
    if re.search(r"\b(short|bear)\b", text):
        return "Short"
    return None


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def discover_leveraged_products(client: SaxoClient, market: str) -> tuple[LeveragedProduct, ...]:
    search_terms = MARKET_SEARCH_TERMS.get(market)
    if not search_terms:
        return ()

    allowed_types = set(LEVERAGED_ASSET_TYPE_NAMES)
    by_identity: dict[tuple[int, str], LeveragedProduct] = {}
    for keywords in search_terms:
        instruments = client.search_instruments(keywords, asset_types=LEVERAGED_ASSET_TYPES)
        for instrument in instruments:
            if instrument.asset_type not in allowed_types:
                continue
            identity = (instrument.uic, instrument.asset_type)
            if identity in by_identity:
                continue
            by_identity[identity] = LeveragedProduct(
                instrument=instrument,
                direction=_direction_from_text(instrument.description, instrument.symbol),
            )

    products = list(by_identity.values())
    products.sort(
        key=lambda item: (
            {"Long": 0, "Short": 1, None: 2}.get(item.direction, 2),
            item.instrument.description.lower(),
            item.instrument.uic,
        )
    )
    return tuple(products)


def product_details(client: SaxoClient, product: LeveragedProduct) -> LeveragedProductDetails:
    raw = client.instrument_details(product.instrument)
    option_data = raw.get("OptionData") if isinstance(raw.get("OptionData"), dict) else {}
    direction = str(raw.get("Direction") or product.direction or "").title() or None
    if direction not in {"Long", "Short"}:
        direction = product.direction

    barrier = _number(
        raw.get("BarrierLevel")
        or raw.get("KnockOutLevel")
        or option_data.get("LowerBarrier")
        or option_data.get("UpperBarrier")
    )
    strike = _number(raw.get("StrikePrice") or option_data.get("Strike"))
    tradable_raw = raw.get("IsTradable")
    is_tradable = tradable_raw if isinstance(tradable_raw, bool) else None

    return LeveragedProductDetails(
        instrument=product.instrument,
        direction=direction,
        is_tradable=is_tradable,
        currency=str(raw.get("CurrencyCode") or raw.get("PriceCurrency") or "") or None,
        barrier=barrier,
        financing_level=_number(raw.get("FinancingLevel")),
        strike=strike,
        default_amount=_number(raw.get("DefaultAmount")),
        minimum_trade_size=_number(raw.get("MinimumTradeSize") or raw.get("MinimumLotSize")),
        minimum_order_value=_number(raw.get("MinimumOrderValue")),
        increment_size=_number(raw.get("IncrementSize")),
        amount_decimals=_integer(raw.get("AmountDecimals")),
    )


def product_label(product: LeveragedProduct) -> str:
    direction = product.direction or "?"
    instrument = product.instrument
    description = instrument.description or instrument.symbol or f"UIC {instrument.uic}"
    return f"{direction} · {description} · {instrument.asset_type} · UIC {instrument.uic}"
