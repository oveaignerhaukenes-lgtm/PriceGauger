from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Any

from saxo_provider import SaxoClient, SaxoError, SaxoInstrument
from trading_desk_products import LeveragedProductDetails


SUPPORTED_INPUT_CURRENCIES = ("NOK", "EUR", "USD")


@dataclass(frozen=True, slots=True)
class ProductSizingQuote:
    market_direction: str | None
    execution_action: str
    input_currency: str
    product_currency: str
    budget_input: float
    fx_product_per_input: float
    unit_price_product: float
    amount: float
    estimated_value_product: float
    estimated_value_input: float


def quote_price(payload: dict[str, Any], *, action: str = "Buy") -> float:
    quote = payload.get("Quote") if isinstance(payload.get("Quote"), dict) else {}
    side = action.strip().title()
    candidates = ("Ask", "Mid", "Bid") if side == "Buy" else ("Bid", "Mid", "Ask")
    for key in candidates:
        value = quote.get(key)
        try:
            price = float(value)
        except (TypeError, ValueError):
            continue
        if price > 0:
            return price
    raise ValueError("Saxo-prisen mangler en positiv Bid/Ask/Mid")


def _normalized_pair_symbol(value: str) -> str:
    return "".join(character for character in value.upper() if character.isalpha())


def _fx_instrument(client: SaxoClient, base: str, quote: str) -> SaxoInstrument | None:
    pair = f"{base}{quote}"
    rows = client.search_instruments(pair, asset_types="FxSpot")
    if not rows:
        rows = client.search_instruments(f"{base} {quote}", asset_types="FxSpot")
    for row in rows:
        symbol = _normalized_pair_symbol(row.symbol)
        description = _normalized_pair_symbol(row.description)
        if pair in symbol or pair in description:
            return row
    return rows[0] if rows else None


def fx_product_per_input(client: SaxoClient, *, input_currency: str, product_currency: str) -> float:
    """Return product-currency units per one input-currency unit using Saxo FX quotes."""
    source = input_currency.strip().upper()
    target = product_currency.strip().upper()
    if source == target:
        return 1.0
    if source not in SUPPORTED_INPUT_CURRENCIES:
        raise ValueError(f"støttet beløpsvaluta er {', '.join(SUPPORTED_INPUT_CURRENCIES)}")

    direct = _fx_instrument(client, source, target)
    if direct is not None:
        return quote_price(client.info_price(direct), action="Sell")

    reverse = _fx_instrument(client, target, source)
    if reverse is None:
        raise SaxoError(f"fant ikke Saxo FX-kurs for {source}/{target}", status="INSTRUMENT_MISSING")
    reverse_rate = quote_price(client.info_price(reverse), action="Buy")
    if reverse_rate <= 0:
        raise ValueError("ugyldig reversert Saxo FX-kurs")
    return 1.0 / reverse_rate


def _amount_step(details: LeveragedProductDetails) -> float:
    candidates = (details.increment_size, details.minimum_trade_size, details.default_amount, 1.0)
    for value in candidates:
        if value is not None and float(value) > 0:
            return float(value)
    return 1.0


def _round_down_to_step(value: float, step: float, amount_decimals: int | None) -> float:
    if value <= 0 or step <= 0:
        return 0.0
    raw = Decimal(str(value))
    quantum = Decimal(str(step))
    multiples = (raw / quantum).to_integral_value(rounding=ROUND_DOWN)
    result = multiples * quantum
    if amount_decimals is not None:
        exponent = Decimal(1).scaleb(-max(0, int(amount_decimals)))
        result = result.quantize(exponent, rounding=ROUND_DOWN)
    return float(result)


def size_from_budget(
    client: SaxoClient,
    details: LeveragedProductDetails,
    *,
    budget: float,
    input_currency: str,
    action: str = "Buy",
) -> ProductSizingQuote:
    """Size a Mini/KO order from spend, while leaving Saxo pre-check authoritative."""
    if budget <= 0:
        raise ValueError("beløpet må være større enn 0")
    if not details.currency:
        raise ValueError("Saxo oppgir ikke produktvaluta; bruk Antall i avansert modus")

    normalized_action = action.strip().title()
    if normalized_action not in {"Buy", "Sell"}:
        raise ValueError("action må være Buy eller Sell")

    unit_price = quote_price(client.info_price(details.instrument), action=normalized_action)
    rate = fx_product_per_input(
        client,
        input_currency=input_currency,
        product_currency=details.currency,
    )
    budget_product = float(budget) * rate
    raw_amount = budget_product / unit_price
    amount = _round_down_to_step(raw_amount, _amount_step(details), details.amount_decimals)

    minimum = float(details.minimum_trade_size or 0.0)
    if minimum > 0 and amount < minimum:
        raise ValueError(
            f"valgt beløp er for lavt for minste handelsstørrelse {minimum:g}; øk beløpet eller velg et annet produkt"
        )
    if amount <= 0:
        raise ValueError("valgt beløp er for lavt til én gyldig enhet av produktet")

    value_product = amount * unit_price
    value_input = value_product / rate
    return ProductSizingQuote(
        market_direction=details.direction,
        execution_action=normalized_action,
        input_currency=input_currency.strip().upper(),
        product_currency=details.currency.strip().upper(),
        budget_input=float(budget),
        fx_product_per_input=rate,
        unit_price_product=unit_price,
        amount=amount,
        estimated_value_product=value_product,
        estimated_value_input=value_input,
    )
