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
    minimum = _positive(
        raw.get("MinimumTradeSize"),
        raw.get("MinimumLotSize"),
        raw.get("DefaultAmount"),
        quantum_from_decimals,
    )
    if minimum is None:
        raise EntrySizingError("instrument details do not expose a legal minimum amount")
    increment = _positive(raw.get("IncrementSize"), quantum_from_decimals)
    if increment is None:
        raise EntrySizingError("instrument details do not expose an amount increment")
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
        increment_size=float(increment),
        contract_size=float(contract_size),
        supported_order_types=supported,
    )


def _quantized_amount(value: float, rules: EntryInstrumentRulesV2, *, upward: bool) -> float:
    step = Decimal(str(rules.increment_size))
    if step <= 0:
        raise EntrySizingError("increment_size must be positive")
    requested = Decimal(str(max(0.0, float(value))))
    units = requested / step
    rounding = ROUND_CEILING if upward else ROUND_FLOOR
    units = units.to_integral_value(rounding=rounding)
    amount = units * step
    minimum = Decimal(str(rules.minimum_amount))
    if upward and amount < minimum:
        minimum_units = (minimum / step).to_integral_value(rounding=ROUND_CEILING)
        amount = minimum_units * step
    quant = Decimal(1).scaleb(-rules.amount_decimals)
    amount = amount.quantize(quant, rounding=rounding)
    return float(amount)


def minimum_legal_amount_v2(rules: EntryInstrumentRulesV2) -> float:
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
    amount: float,
    side: str,
) -> dict[str, Any]:
    return client._get(
        "trade/v1/infoprices",
        params={
            "AccountKey": account_key,
            "Amount": float(amount),
            "Uic": int(instrument.uic),
            "AssetType": instrument.asset_type,
            "FieldGroups": "Quote,PriceInfo,InstrumentPriceDetails",
        },
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
    # Some Saxo responses expose only instrument-currency Cost plus a conversion
    # rate. The caller converts this fallback through the documented rate.
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
    if amount + 1e-12 < minimum_legal_amount_v2(rules):
        raise EntrySizingError("amount is below the legal instrument minimum")

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
    minimum = minimum_legal_amount_v2(rules)
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
        raise EntrySizingError("minimum legal amount does not pass Saxo precheck and Margin Envelope")
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
) -> tuple[EntryInstrumentRulesV2, EntryPrecheckV2]:
    """Verify cost/tradability with the smallest legal order without submitting it.

    The permissive envelope here is not an execution authorization. It exists only
    to collect Saxo's precheck cost/margin metadata for explicit product admission.
    Every real OPEN is re-sized against the pilot-specific hard envelope later.
    """
    rules = load_entry_instrument_rules_v2(client, account_key=account_key, instrument=instrument)
    amount = minimum_legal_amount_v2(rules)
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
        external_reference=external_reference,
    )
    if not _precheck_is_clear(result.raw):
        raise EntrySizingError(
            f"minimum-entry precheck blocked: {result.precheck_result}; disclaimers={result.disclaimers_present}"
        )
    return rules, result


__all__ = [
    "EntryInstrumentRulesV2",
    "EntryPrecheckV2",
    "EntrySizingError",
    "EntrySizingResultV2",
    "find_largest_legal_entry_v2",
    "live_open_order_payload_v2",
    "load_entry_instrument_rules_v2",
    "minimum_legal_amount_v2",
    "precheck_entry_amount_v2",
    "preflight_minimum_entry_v2",
]
