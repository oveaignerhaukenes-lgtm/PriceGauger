"""LIVE V3 OPEN/ADD broker validation.

The persisted NOK budget is cash/capital allocated to the trader, not a ceiling
on leveraged gross market notional.  Until Saxo margin/cash impact is wired in
as a broker-native metric, do not derive spend from price * CFD amount: doing so
turns leverage into a false cash requirement and can block Saxo's minimum lot.

This boundary still validates account currency, instrument rules, tradable step,
market-price diagnostics. The runtime performs exactly one Saxo precheck after sizing; Saxo remains the final authority
on whether the requested leveraged order is admissible.
"""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from autotrader_open_sizing_v2 import load_entry_instrument_rules_v2,_info_price,_extract_price
from autotrader_v3_execution_policy_v1 import ExecutionPolicyV3


class V3CapitalCapReached(ValueError):
    """Expected capacity saturation, distinct from malformed/missing broker evidence."""


def capital_requirement_nok_v3(*, precheck: dict, side: str, account_currency: str) -> float:
    """Return Saxo broker-native capital requirement for one prechecked order."""
    currency=str(account_currency or '').strip().upper()
    if currency!='NOK':
        raise ValueError('V3 capital requirement requires a NOK Saxo account')
    normalized=str(side or '').strip().title()
    if normalized not in {'Buy','Sell'}:
        raise ValueError('V3 side must be Buy or Sell')
    impact=precheck.get("MarginImpactBuySell")
    impact=impact if isinstance(impact,dict) else {}
    impact_currency=str(impact.get('Currency') or '').strip().upper()
    suffix='Buy' if normalized=='Buy' else 'Sell'
    raw_margin=impact.get(f'InitialMargin{suffix}',impact.get('InitialMargin'))
    try:
        margin=float(raw_margin) if raw_margin is not None else None
    except (TypeError,ValueError):
        margin=None
    if margin is not None and margin > 0:
        if impact_currency and impact_currency!='NOK':
            raise ValueError(f'V3 margin requirement currency is {impact_currency}, expected NOK')
        return margin
    raw_cash=precheck.get('EstimatedCashRequired')
    try:
        cash=float(raw_cash) if raw_cash is not None else None
    except (TypeError,ValueError):
        cash=None
    cash_currency=str(precheck.get('EstimatedCashRequiredCurrency') or '').strip().upper()
    if cash is not None and cash >= 0:
        if cash_currency and cash_currency!='NOK':
            raise ValueError(f'V3 cash requirement currency is {cash_currency}, expected NOK')
        return cash
    raise ValueError('Saxo precheck did not expose broker capital requirement')


def enforce_execution_policy_precheck_v3(*, precheck: dict, side: str,
                                         account_currency: str, policy: ExecutionPolicyV3,
                                         current_same_side_amount: float = 0.0,
                                         order_amount: float | None = None) -> float:
    """Enforce the PG capital allocation against the resulting same-side position.

    Saxo's precheck exposes the margin impact of the order being checked.  For an
    incremental pyramiding strategy that is not enough on its own: validating each
    0.01 tranche independently would let a trader accumulate an arbitrarily large
    position while every individual step stayed below the configured cap.

    For ADD we therefore conservatively project the current per-unit initial-margin
    requirement across the post-trade same-side inventory.  This keeps the per-trader
    allocation meaningful even though Saxo margin is pooled at client level.
    """
    step_required=capital_requirement_nok_v3(
        precheck=precheck,side=side,account_currency=account_currency)
    current=max(0.0,float(current_same_side_amount or 0.0))
    if current > 1e-12:
        if order_amount is None or float(order_amount) <= 1e-12:
            raise ValueError('V3 cumulative capital check requires positive order amount')
        amount=float(order_amount)
        required=step_required * ((current + amount) / amount)
    else:
        required=step_required
    cap=float(policy.max_notional_nok)
    if required > cap + 1e-9:
        raise V3CapitalCapReached(
            f'V3 cumulative capital requirement {required:.2f} NOK exceeds configured cap {cap:.2f} NOK')
    return required

@dataclass(frozen=True, slots=True)
class CappedMutationV3:
    requested_amount: float
    permitted_amount: float
    unit_notional_nok: float
    max_notional_nok: float


def cap_open_add_amount_v3(*,broker,account_key:str,account_currency:str,instrument,side:str,
                           requested_amount:float,policy:ExecutionPolicyV3,current_same_side_amount:float=0.0)->CappedMutationV3:
    currency=str(account_currency).strip().upper()
    if not currency:
        raise ValueError('V3 Saxo account currency unavailable')
    if currency!='NOK':
        raise ValueError('V3 NOK capital policy requires a NOK Saxo account')
    rules=load_entry_instrument_rules_v2(broker.client,account_key=account_key,instrument=instrument)
    requested=Decimal(str(requested_amount))
    if requested <= 0:
        raise ValueError('V3 requested amount must be positive')
    step=Decimal(str(rules.increment_size))
    permitted=(requested/step).to_integral_value(rounding=ROUND_DOWN)*step
    if permitted < Decimal(str(rules.minimum_amount)):
        raise ValueError('V3 requested amount is below Saxo minimum order amount')

    info=_info_price(broker.client,account_key=account_key,instrument=instrument,amount=float(permitted),side=side)
    price=_extract_price(info,side,require_side_price=True)
    # Diagnostic only: do not spend a Saxo precheck here merely to obtain FX.
    # The runtime owns the single authoritative precheck immediately before POST.
    unit=float(price)
    if unit<=0:
        raise ValueError('invalid V3 unit notional')

    # Diagnostic only.  Gross leveraged notional is deliberately NOT compared
    # with the cash allocation.  A future broker-native margin/cash-impact value
    # can enforce policy.max_notional_nok without changing this public contract.
    return CappedMutationV3(float(requested_amount),float(permitted),unit,policy.max_notional_nok)


__all__ = [
    "CappedMutationV3",
    "cap_open_add_amount_v3",
    "capital_requirement_nok_v3",
    "enforce_execution_policy_precheck_v3",
    "V3CapitalCapReached",
]
