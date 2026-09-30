"""LIVE V3 OPEN/ADD broker validation.

The persisted NOK budget is cash/capital allocated to the trader, not a ceiling
on leveraged gross market notional.  Until Saxo margin/cash impact is wired in
as a broker-native metric, do not derive spend from price * CFD amount: doing so
turns leverage into a false cash requirement and can block Saxo's minimum lot.

This boundary still validates account currency, instrument rules, tradable step,
market price/FX diagnostics and Saxo precheck.  Saxo remains the final authority
on whether the requested leveraged order is admissible.
"""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from autotrader_open_sizing_v2 import load_entry_instrument_rules_v2,_info_price,_extract_price,_conversion_factor
from autotrader_v3_execution_policy_v1 import ExecutionPolicyV3
from saxo_trading import SaxoOrderRequest

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
    probe=SaxoOrderRequest(account_key=account_key,instrument=instrument,amount=float(permitted),buy_sell=side)
    pre=broker.precheck(probe)
    factor=_conversion_factor(pre,source_currency=rules.currency,account_currency='NOK')
    unit=float(price)*float(factor)
    if unit<=0:
        raise ValueError('invalid V3 unit notional')

    # Diagnostic only.  Gross leveraged notional is deliberately NOT compared
    # with the cash allocation.  A future broker-native margin/cash-impact value
    # can enforce policy.max_notional_nok without changing this public contract.
    return CappedMutationV3(float(requested_amount),float(permitted),unit,policy.max_notional_nok)
