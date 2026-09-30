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
                           requested_amount:float,policy:ExecutionPolicyV3,current_same_side_amount:float=0.0)->CappedMutationV3:
    currency=str(account_currency).strip().upper()
    if not currency:
        raise ValueError('V3 Saxo account currency unavailable')
    if currency!='NOK':
        raise ValueError('V3 NOK exposure policy requires a NOK Saxo account')
    rules=load_entry_instrument_rules_v2(broker.client,account_key=account_key,instrument=instrument)
    info=_info_price(broker.client,account_key=account_key,instrument=instrument,amount=requested_amount,side=side)
    price=_extract_price(info,side,require_side_price=True)
    probe=SaxoOrderRequest(account_key=account_key,instrument=instrument,amount=requested_amount,buy_sell=side)
    pre=broker.precheck(probe)
    factor=_conversion_factor(pre,source_currency=rules.currency,account_currency='NOK')
    # For Saxo index CFDs Amount is already the tradable exposure unit.  The
    # reference-data ContractSize/PriceToContractFactor is not an extra amount
    # multiplier here; multiplying by it can inflate one 0.01 ticket into a
    # fictitious full-contract notional and make every legal minimum look over cap.
    unit=float(price)*float(factor)
    if unit<=0: raise ValueError('invalid V3 unit notional')
    step=Decimal(str(rules.increment_size))
    raw=Decimal(str(policy.max_notional_nok))/Decimal(str(unit))
    max_total=(raw/step).to_integral_value(rounding=ROUND_DOWN)*step
    current=Decimal(str(abs(float(current_same_side_amount))))
    room=max(Decimal(0),max_total-current)
    permitted=min(Decimal(str(requested_amount)),room)
    permitted=(permitted/step).to_integral_value(rounding=ROUND_DOWN)*step
    if permitted < Decimal(str(rules.minimum_amount)):
        raise ValueError('V3 exposure cap leaves less than Saxo minimum order amount')
    return CappedMutationV3(float(requested_amount),float(permitted),unit,policy.max_notional_nok)
