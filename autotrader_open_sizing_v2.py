from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import math
from typing import Any

from autotrader_live_close_v1 import _post_once, _precheck_is_clear
from autotrader_margin_envelope_v2 import (
    AutoTraderMarginDecisionV2,
    AutoTraderMarginEnvelopeV2,
    AutoTraderMarginProposalV2,
    AutoTraderMarginStateV2,
    evaluate_margin_envelope_v2,
)
from saxo_provider import SaxoClient, SaxoError, SaxoInstrument


@dataclass(frozen=True, slots=True)
class EntryInstrumentRulesV2:
    uic: int
    asset_type: str
    currency: str
    is_tradable: bool
    non_tradable_reason: str
    amount_decimals: int
    minimum_amount: float
    increment_size: float
    contract_size: float
    supported_order_types: tuple[str, ...]
    amount_quantum: float = 1.0
    reference_minimum_amount: float | None = None
    minimum_order_value: float | None = None


@dataclass(frozen=True, slots=True)
class EntryMinimumResolutionV2:
    amount: float
    source: str
    reference_minimum_amount: float | None
    minimum_order_value: float | None


@dataclass(frozen=True, slots=True)
class EntryPrecheckV2:
    amount: float
    buy_sell: str
    price: float
    notional_account: float
    initial_margin_account: float
    available_margin_current_account: float
    available_margin_after_account: float
    estimated_cost_account: float
    precheck_result: str
    disclaimers_present: bool
    margin_decision: AutoTraderMarginDecisionV2
    raw: dict[str, Any]

    @property
    def allowed(self) -> bool:
        return bool(
            self.precheck_result.lower() == "ok"
            and not self.disclaimers_present
            and self.margin_decision.allowed
        )


@dataclass(frozen=True, slots=True)
class EntrySizingResultV2:
    rules: EntryInstrumentRulesV2
    amount: float
    final_precheck: EntryPrecheckV2
    precheck_count: int


class EntrySizingError(RuntimeError):
    pass


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _positive(*values: Any) -> float | None:
    for value in values:
        parsed = _number(value)
        if parsed is not None and parsed > 0:
            return parsed
    return None


def _max_positive(*values: Any) -> float | None:
    parsed = [_number(value) for value in values]
    positive = [value for value in parsed if value is not None and value > 0]
    return max(positive) if positive else None


def _integer(value: Any, default: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _normalize_side(direction: str) -> str:
    value = str(direction).strip().upper()
    if value == "LONG":
        return "Buy"
    if value == "SHORT":
        return "Sell"
    raise ValueError("entry direction must be LONG or SHORT")


def load_entry_instrument_rules_v2(
    client: SaxoClient,
    *,
    account_key: str,
    instrument: SaxoInstrument,
) -> EntryInstrumentRulesV2:
    raw = client._get(
        f"ref/v1/instruments/details/{int(instrument.uic)}/{instrument.asset_type}",
        params={"AccountKey": account_key, "FieldGroups": "MarketData"},
    )
    asset_type = str(raw.get("AssetType") or instrument.asset_type).strip()
    if asset_type != instrument.asset_type:
        raise EntrySizingError("instrument details returned a different AssetType")

    tradable_raw = raw.get("IsTradable")
    is_tradable = bool(tradable_raw) if isinstance(tradable_raw, bool) else False
    non_tradable_reason = str(raw.get("NonTradableReason") or "None")
    if not is_tradable:
        raise EntrySizingError(f"instrument is not tradable: {non_tradable_reason}")

    decimals = _integer(raw.get("AmountDecimals"), 0)
    quantum_from_decimals = 10.0 ** (-decimals)

    # Saxo's DefaultAmount is only a ticket/UI default. It is not a legal
    # minimum. Likewise InstrumentDetails.IncrementSize is a price increment,
    # not an amount increment. The old implementation used both as amount rules,
    # which made fractional CFDs such as CfdOnIndex appear 100x too large.
    reference_minimum = _max_positive(
        raw.get("MinimumTradeSize"),
        raw.get("MinimumLotSize"),
    )
    minimum = max(float(quantum_from_decimals), float(reference_minimum or quantum_from_decimals))

    amount_step = float(quantum_from_decimals)
    lot_size_type = str(raw.get("LotSizeType") or "").strip().lower()
    lot_size = _positive(raw.get("LotSize"))
    if lot_size is not None and lot_size_type == "oddlotsnotallowed":
        amount_step = max(amount_step, float(lot_size))

    contract_size = _positive(raw.get("ContractSize"), raw.get("PriceToContractFactor"))
    if contract_size is None:
        raise EntrySizingError("instrument details do not expose ContractSize/PriceToContractFactor")

    supported_raw = raw.get("SupportedOrderTypes") or ()
    if isinstance(supported_raw, list):
        supported = tuple(str(item) for item in supported_raw)
    else:
        supported = ()
    if supported and "Market" not in supported:
        raise EntrySizingError("instrument does not advertise Market order support")

    currency = str(raw.get("CurrencyCode") or raw.get("PriceCurrency") or "").strip().upper()
    if not currency:
        raise EntrySizingError("instrument details do not expose price currency")

    return EntryInstrumentRulesV2(
        uic=int(instrument.uic),
        asset_type=instrument.asset_type,
        currency=currency,
        is_tradable=True,
        non_tradable_reason=non_tradable_reason,
        amount_decimals=decimals,
        minimum_amount=float(minimum),
        increment_size=float(amount_step),
        contract_size=float(contract_size),
        supported_order_types=supported,
        amount_quantum=float(quantum_from_decimals),
        reference_minimum_amount=None if reference_minimum is None else float(reference_minimum),
        minimum_order_value=_positive(raw.get("MinimumOrderValue")),
    )


def _quantized_amount(value: float, rules: EntryInstrumentRulesV2, *, upward: bool) -> float:
    step = Decimal(str(rules.increment_size))
    if step <= 0:
        raise EntrySizingError("amount increment must be positive")
    requested = Decimal(str(max(0.0, float(value))))
    units = requested / step
    rounding = ROUND_CEILING if upward else ROUND_FLOOR
    units = units.to_integral_value(rounding=rounding)
    amount = units * step
    quantum = Decimal(str(rules.amount_quantum))
    if upward and amount < quantum:
        quantum_units = (quantum / step).to_integral_value(rounding=ROUND_CEILING)
        amount = max(step, quantum_units * step)
    quant = Decimal(1).scaleb(-rules.amount_decimals)
    amount = amount.quantize(quant, rounding=rounding)
    return float(amount)


def minimum_legal_amount_v2(rules: EntryInstrumentRulesV2) -> float:
    """Legacy reference-data floor.

    New execution code must additionally use resolve_minimum_entry_amount_v2(),
    because Saxo account-specific InfoPrice/precheck is the final authority.
    """
    return _quantized_amount(rules.minimum_amount, rules, upward=True)


def _extract_price(payload: dict[str, Any], side: str) -> float:
    quote = payload.get("Quote") if isinstance(payload.get("Quote"), dict) else {}
    price_info = payload.get("PriceInfo") if isinstance(payload.get("PriceInfo"), dict) else {}
    if side == "Buy":
        candidates = (quote.get("Ask"), price_info.get("Ask"), quote.get("Mid"), price_info.get("Mid"))
    else:
        candidates = (quote.get("Bid"), price_info.get("Bid"), quote.get("Mid"), price_info.get("Mid"))
    price = _positive(*candidates)
    if price is None:
        raise EntrySizingError("InfoPrice did not return an executable side price")
    return float(price)


def _info_price(
    client: SaxoClient,
    *,
    account_key: str,
    instrument: SaxoInstrument,
    amount: float | None,
    side: str,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "AccountKey": account_key,
        "Uic": int(instrument.uic),
        "AssetType": instrument.asset_type,
        "FieldGroups": "Quote,PriceInfo,InstrumentPriceDetails",
    }
    if amount is not None:
        params["Amount"] = float(amount)
    return client._get("trade/v1/infoprices", params=params)


def resolve_minimum_entry_amount_v2(
    client: SaxoClient,
    *,
    account_key: str,
    instrument: SaxoInstrument,
    rules: EntryInstrumentRulesV2,
) -> EntryMinimumResolutionV2:
    """Resolve an account-specific minimum candidate without submitting an order.

    Saxo documents InfoPrice.Amount as optional and says that omitting it defaults
    to the minimal order size for the instrument. The chosen amount is returned in
    Quote.Amount. We prefer that account-specific value over generic reference
    metadata. If Saxo does not return a usable amount, we fall back to the smallest
    representable amount quantum and let order precheck prove or reject it.
    """
    info_amount: float | None = None
    try:
        payload = _info_price(
            client,
            account_key=account_key,
            instrument=instrument,
            amount=None,
            side="Buy",
        )
        quote = payload.get("Quote") if isinstance(payload.get("Quote"), dict) else {}
        info_amount = _positive(quote.get("Amount"))
    except SaxoError:
        info_amount = None

    if info_amount is not None:
        candidate = _quantized_amount(float(info_amount), rules, upward=True)
        source = "SAXO_INFOPRICE_DEFAULT_MINIMUM"
    else:
        candidate = _quantized_amount(float(rules.amount_quantum), rules, upward=True)
        source = "AMOUNT_DECIMALS_PROBE"

    if candidate <= 0:
        raise EntrySizingError("could not resolve a positive minimum-entry candidate")
    return EntryMinimumResolutionV2(
        amount=float(candidate),
        source=source,
        reference_minimum_amount=rules.reference_minimum_amount,
        minimum_order_value=rules.minimum_order_value,
    )


def _open_payload(
    *,
    account_key: str,
    instrument: SaxoInstrument,
    amount: float,
    buy_sell: str,
    external_reference: str,
    include_precheck_fields: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "AccountKey": account_key,
        "Amount": float(amount),
        "AssetType": instrument.asset_type,
        "BuySell": buy_sell,
        "ExternalReference": external_reference[:50],
        "IsForceOpen": False,
        "ManualOrder": False,
        "OrderDuration": {"DurationType": "DayOrder"},
        "OrderType": "Market",
        "Uic": int(instrument.uic),
    }
    if include_precheck_fields:
        payload["FieldGroups"] = ["MarginImpactBuySell", "Costs"]
    return payload


def live_open_order_payload_v2(
    *,
    account_key: str,
    instrument: SaxoInstrument,
    amount: float,
    direction: str,
    external_reference: str,
) -> dict[str, Any]:
    return _open_payload(
        account_key=account_key,
        instrument=instrument,
        amount=amount,
        buy_sell=_normalize_side(direction),
        external_reference=external_reference,
        include_precheck_fields=False,
    )


def _conversion_factor(
    precheck: dict[str, Any],
    *,
    source_currency: str,
    account_currency: str,
) -> float:
    if source_currency.upper() == account_currency.upper():
        return 1.0
    rate = _positive(precheck.get("InstrumentToAccountConversionRate"))
    if rate is None:
        raise EntrySizingError(
            f"precheck cannot convert {source_currency} to account currency {account_currency}"
        )
    return float(rate)


def _sum_cost_data(value: Any) -> float | None:
    if not isinstance(value, dict):
        return None
    total = 0.0
    found = False
    for item in value.values():
        parsed = _number(item)
        if parsed is None:
            continue
        total += abs(parsed)
        found = True
    return total if found else None


def _cost_account(precheck: dict[str, Any]) -> float:
    total = _number(precheck.get("EstimatedTotalCostInAccountCurrency"))
    if total is not None:
        return max(0.0, abs(total))
    direct = _sum_cost_data(precheck.get("CostInAccountCurrency"))
    if direct is not None:
        return max(0.0, direct)
    direct = _sum_cost_data(precheck.get("Cost"))
    if direct is not None:
        rate = _positive(precheck.get("InstrumentToAccountConversionRate"))
        if rate is not None:
            return max(0.0, direct * rate)
    return 0.0


def precheck_entry_amount_v2(
    client: SaxoClient,
    *,
    account_key: str,
    account_currency: str,
    instrument: SaxoInstrument,
    rules: EntryInstrumentRulesV2,
    direction: str,
    amount: float,
    envelope: AutoTraderMarginEnvelopeV2,
    controlled_capital: float,
    external_reference: str,
) -> EntryPrecheckV2:
    side = _normalize_side(direction)
    amount = _quantized_amount(amount, rules, upward=False)
    if amount + 1e-12 < float(rules.amount_quantum):
        raise EntrySizingError("amount is below the instrument amount precision")

    info = _info_price(
        client,
        account_key=account_key,
        instrument=instrument,
        amount=amount,
        side=side,
    )
    price = _extract_price(info, side)

    payload = _open_payload(
        account_key=account_key,
        instrument=instrument,
        amount=amount,
        buy_sell=side,
        external_reference=external_reference,
        include_precheck_fields=True,
    )
    precheck = _post_once(client, "trade/v2/orders/precheck", payload)
    result = str(precheck.get("PreCheckResult") or "")
    disclaimers = bool(precheck.get("PreTradeDisclaimers"))

    impact = precheck.get("MarginImpactBuySell")
    if not isinstance(impact, dict):
        raise EntrySizingError("Saxo precheck did not return MarginImpactBuySell")
    impact_currency = str(impact.get("Currency") or rules.currency).strip().upper()
    if impact_currency == account_currency.upper():
        impact_factor = 1.0
    elif impact_currency == rules.currency.upper():
        impact_factor = _conversion_factor(
            precheck,
            source_currency=rules.currency,
            account_currency=account_currency,
        )
    else:
        raise EntrySizingError(
            f"margin-impact currency {impact_currency} cannot be proven convertible from instrument currency {rules.currency}"
        )

    suffix = "Buy" if side == "Buy" else "Sell"
    margin = _number(impact.get(f"InitialMargin{suffix}"))
    available_current = _number(impact.get("InitialMarginAvailableCurrent"))
    available_after = _number(impact.get(f"InitialMarginAvailable{suffix}"))
    if margin is None or available_current is None or available_after is None:
        raise EntrySizingError("Saxo precheck returned incomplete initial-margin impact")

    notional_factor = _conversion_factor(
        precheck,
        source_currency=rules.currency,
        account_currency=account_currency,
    )
    notional = price * float(amount) * float(rules.contract_size) * notional_factor
    cost = _cost_account(precheck)

    state = AutoTraderMarginStateV2(
        currency=account_currency,
        controlled_capital=float(controlled_capital),
        initial_margin_used=0.0,
        gross_notional_exposure=0.0,
        free_capital=max(0.0, available_current * impact_factor),
    )
    proposal = AutoTraderMarginProposalV2(
        currency=account_currency,
        resulting_controlled_capital=float(controlled_capital),
        resulting_initial_margin=max(0.0, margin * impact_factor),
        resulting_gross_notional=max(0.0, notional),
        resulting_free_capital=max(0.0, available_after * impact_factor),
        estimated_transaction_cost=max(0.0, cost),
        source="saxo-precheck",
    )
    margin_decision = evaluate_margin_envelope_v2(envelope, state, proposal)
    return EntryPrecheckV2(
        amount=float(amount),
        buy_sell=side,
        price=price,
        notional_account=max(0.0, notional),
        initial_margin_account=max(0.0, margin * impact_factor),
        available_margin_current_account=max(0.0, available_current * impact_factor),
        available_margin_after_account=max(0.0, available_after * impact_factor),
        estimated_cost_account=max(0.0, cost),
        precheck_result=result,
        disclaimers_present=disclaimers,
        margin_decision=margin_decision,
        raw=precheck,
    )


def _attempt_precheck(*args: Any, **kwargs: Any) -> EntryPrecheckV2 | None:
    try:
        return precheck_entry_amount_v2(*args, **kwargs)
    except (SaxoError, EntrySizingError):
        return None


def find_largest_legal_entry_v2(
    client: SaxoClient,
    *,
    account_key: str,
    account_currency: str,
    instrument: SaxoInstrument,
    direction: str,
    envelope: AutoTraderMarginEnvelopeV2,
    controlled_capital: float,
    external_reference_prefix: str,
    max_prechecks: int = 20,
) -> EntrySizingResultV2:
    rules = load_entry_instrument_rules_v2(
        client,
        account_key=account_key,
        instrument=instrument,
    )
    resolution = resolve_minimum_entry_amount_v2(
        client,
        account_key=account_key,
        instrument=instrument,
        rules=rules,
    )
    minimum = float(resolution.amount)
    count = 0

    def check(amount: float) -> EntryPrecheckV2 | None:
        nonlocal count
        if count >= max_prechecks:
            return None
        count += 1
        item = _attempt_precheck(
            client,
            account_key=account_key,
            account_currency=account_currency,
            instrument=instrument,
            rules=rules,
            direction=direction,
            amount=amount,
            envelope=envelope,
            controlled_capital=controlled_capital,
            external_reference=f"{external_reference_prefix}-pc{count}",
        )
        if item is None or not item.allowed:
            return None
        return item

    first = check(minimum)
    if first is None:
        raise EntrySizingError("account-specific minimum amount does not pass Saxo precheck and Margin Envelope")
    best = first
    low_units = int(round(best.amount / rules.increment_size))
    high_units: int | None = None

    while count < max_prechecks - 2:
        candidate_units = max(low_units + 1, low_units * 2)
        candidate_amount = _quantized_amount(candidate_units * rules.increment_size, rules, upward=False)
        item = check(candidate_amount)
        if item is None:
            high_units = candidate_units
            break
        best = item
        low_units = candidate_units

    if high_units is None:
        return EntrySizingResultV2(rules=rules, amount=best.amount, final_precheck=best, precheck_count=count)

    while high_units - low_units > 1 and count < max_prechecks:
        mid_units = (low_units + high_units) // 2
        candidate_amount = _quantized_amount(mid_units * rules.increment_size, rules, upward=False)
        item = check(candidate_amount)
        if item is None:
            high_units = mid_units
        else:
            best = item
            low_units = mid_units

    return EntrySizingResultV2(
        rules=rules,
        amount=best.amount,
        final_precheck=best,
        precheck_count=count,
    )


def preflight_minimum_entry_v2(
    client: SaxoClient,
    *,
    account_key: str,
    account_currency: str,
    instrument: SaxoInstrument,
    direction: str,
    external_reference: str,
    max_prechecks: int = 16,
) -> tuple[EntryInstrumentRulesV2, EntryPrecheckV2]:
    """Discover and verify the smallest account-specific order without submitting it.

    Reference Data is used for amount precision, lot rules and metadata, but Saxo's
    account-specific InfoPrice and order precheck remain authoritative. If the
    default InfoPrice amount is unavailable or rejected, the resolver probes upward
    in legal amount increments until it finds the first precheck-accepted size.
    No order-placement endpoint is called by this function.
    """
    rules = load_entry_instrument_rules_v2(client, account_key=account_key, instrument=instrument)
    resolution = resolve_minimum_entry_amount_v2(
        client,
        account_key=account_key,
        instrument=instrument,
        rules=rules,
    )
    huge = 1e18
    envelope = AutoTraderMarginEnvelopeV2(
        currency=account_currency,
        capital_control_limit=huge,
        max_initial_margin=huge,
        max_notional_exposure=huge,
        max_effective_leverage=huge,
        minimum_free_capital=0.0,
        enabled=True,
    )

    count = 0

    def check(amount: float) -> EntryPrecheckV2 | None:
        nonlocal count
        if count >= max_prechecks:
            return None
        count += 1
        try:
            result = precheck_entry_amount_v2(
                client,
                account_key=account_key,
                account_currency=account_currency,
                instrument=instrument,
                rules=rules,
                direction=direction,
                amount=amount,
                envelope=envelope,
                controlled_capital=huge,
                external_reference=f"{external_reference}-min{count}",
            )
        except (SaxoError, EntrySizingError):
            return None
        return result if _precheck_is_clear(result.raw) else None

    step = float(rules.increment_size)
    start = _quantized_amount(float(resolution.amount), rules, upward=True)
    first = check(start)
    if first is not None:
        return rules, first

    low_units = max(0, int(round(start / step)))
    high_units: int | None = None
    best: EntryPrecheckV2 | None = None

    while count < max_prechecks:
        candidate_units = max(low_units + 1, low_units * 2)
        candidate = _quantized_amount(candidate_units * step, rules, upward=True)
        item = check(candidate)
        if item is not None:
            high_units = candidate_units
            best = item
            break
        low_units = candidate_units

    if best is None or high_units is None:
        raise EntrySizingError("could not discover an account-specific minimum order accepted by Saxo precheck")

    while high_units - low_units > 1 and count < max_prechecks:
        mid_units = (low_units + high_units) // 2
        candidate = _quantized_amount(mid_units * step, rules, upward=True)
        item = check(candidate)
        if item is None:
            low_units = mid_units
        else:
            high_units = mid_units
            best = item

    return rules, best


__all__ = [
    "EntryInstrumentRulesV2",
    "EntryMinimumResolutionV2",
    "EntryPrecheckV2",
    "EntrySizingError",
    "EntrySizingResultV2",
    "find_largest_legal_entry_v2",
    "live_open_order_payload_v2",
    "load_entry_instrument_rules_v2",
    "minimum_legal_amount_v2",
    "precheck_entry_amount_v2",
    "preflight_minimum_entry_v2",
    "resolve_minimum_entry_amount_v2",
]
