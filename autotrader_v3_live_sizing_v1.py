"""LIVE V3 OPEN/ADD sizing against a submission-time NOK notional ceiling."""
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
                           requested_amount:float,policy:ExecutionPolicyV3)->CappedMutationV3:
    if str(account_currency).upper()!='NOK':
        raise ValueError('V3 NOK exposure policy requires a NOK Saxo account')
    rules=load_entry_instrument_rules_v2(broker.client,account_key=account_key,instrument=instrument)
    info=_info_price(broker.client,account_key=account_key,instrument=instrument,amount=requested_amount,side=side)
    price=_extract_price(info,side,require_side_price=True)
    probe=SaxoOrderRequest(account_key=account_key,instrument=instrument,amount=requested_amount,buy_sell=side)
    pre=broker.precheck(probe)
    factor=_conversion_factor(pre,source_currency=rules.currency,account_currency='NOK')
    unit=float(price)*float(rules.contract_size)*float(factor)
    if unit<=0: raise ValueError('invalid V3 unit notional')
    step=Decimal(str(rules.increment_size))
    raw=Decimal(str(policy.max_notional_nok))/Decimal(str(unit))
    permitted=(raw/step).to_integral_value(rounding=ROUND_DOWN)*step
    permitted=min(Decimal(str(requested_amount)),permitted)
    if permitted < Decimal(str(rules.minimum_amount)):
        raise ValueError('V3 exposure cap is below Saxo minimum order amount')
    return CappedMutationV3(float(requested_amount),float(permitted),unit,policy.max_notional_nok)
