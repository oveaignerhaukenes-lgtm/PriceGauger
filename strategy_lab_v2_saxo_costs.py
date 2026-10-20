"""Saxo GET-only cost calibration for Strategy Lab v2 historical PAPER replay.

The *current* Saxo account/quote/cost illustration is a SCENARIO for historical
replay, not an archived fill, historical spread, guarantee of margin, or FX.
Unknown evidence fails closed for the "Saxo calibrated" mode.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from urllib.parse import quote

from saxo_provider import SaxoInstrument
from saxo_low_friction_candidates_v2 import _quote_fields
from product_browser_keyword_cost_v1 import _fx_mid,_verified_cost_probe
from strategy_lab_v2_replay import ReplayCostsV2


@dataclass(frozen=True,slots=True)
class SaxoReplayCostEvidenceV2:
    account_id:str
    product_uic:int
    asset_type:str
    price_currency:str|None
    account_currency:str
    price:float|None
    point_value_nok:float|None
    fx_source:str
    spread_bps:float|None
    fixed_commission_nok:float|None
    minimum_trade_size:float|None
    increment_size:float|None
    status:str
    notes:tuple[str,...]


def saxobank_accounts_v2(client)->tuple[dict,...]:
    result=client._get("port/v1/accounts/me").get("Data") or []
    return tuple(
        {"account_key":str(x["AccountKey"]),"account_id":str(x.get("AccountId") or ""),
         "currency":str(x.get("Currency") or "")}
        for x in result if isinstance(x,dict) and x.get("AccountKey")
    )


def saxo_replay_costs_v2(client,*,source,account:dict,
                         quantity:float=.01)->SaxoReplayCostEvidenceV2:
    account_id=str(account.get("account_id") or "")
    key=str(account.get("account_key") or "")
    if not key or not account_id:
        raise ValueError("explicit selected Saxo account required")
    instrument=SaxoInstrument(
        asset=str(source.market_name),uic=int(source.provider_instrument_id),
        asset_type=str(source.asset_type),symbol=str(source.symbol or ""),
    )
    notes=[]
    details={}
    try:
        response=client._get(f"ref/v1/instruments/details/{instrument.uic}/{instrument.asset_type}")
        details=response if isinstance(response,dict) else {}
    except Exception as exc:
        notes.append(f"Saxo instrument details unavailable: {type(exc).__name__}")
    currency=str(details.get("PriceCurrency") or details.get("CurrencyCode") or "").upper()
    if instrument.asset_type=="FxSpot":
        import re
        sym=re.sub("[^A-Z]","",instrument.symbol.upper())
        if len(sym)>=6:currency=sym[3:6]
    multiplier=None
    try:
        multiplier=float(details.get("ContractSize") or source.price_multiplier or 0)
        if not isfinite(multiplier) or multiplier<=0: multiplier=None
    except (TypeError,ValueError):
        multiplier=None
    min_trade=step=None
    for field,var in (("MinimumTradeSize","min"),("IncrementSize","step")):
        try:
            v=float(details[field])
            if isfinite(v) and v>0:
                if var=="min":min_trade=v
                else:step=v
        except (KeyError,ValueError,TypeError):
            pass
    price=spread_bps=None
    try:
        raw=client.info_price(instrument)
        bid,ask,_spread=_quote_fields(raw)
        if bid is not None and ask is not None and ask>=bid and bid>0:
            price=(bid+ask)/2
            spread_bps=10000*(ask-bid)/price
    except Exception as exc:
        notes.append(f"Saxo quote unavailable: {type(exc).__name__}")
    fx,fxsource=(_fx_mid(client,currency,{})
                 if currency else (None,"Saxo price currency unknown"))
    point_value=(float(multiplier)*float(fx)
                 if multiplier is not None and fx is not None else None)
    fee=None
    if price is not None and min_trade is not None:
        long,short,fee_currency,_,_,err=_verified_cost_probe(
            client,account=type("ReadonlyAccount",(),{"account_key":key})(),
            instrument=instrument,amount=max(float(quantity),min_trade),price=price,
        )
        if err:
            notes.append("Saxo cost illustration unavailable: "+err)
        elif long is not None and short is not None:
            # Long/short asymmetry cannot be described by one fixed fee;
            # use the conservative larger observed fee for scenario.
            fee=max(long,short)
            fee_currency=str(fee_currency or "")
            if fee_currency!="NOK":
                rate,fee_source=_fx_mid(client,fee_currency,{}) if fee_currency else (None,"unknown")
                if rate is None:
                    fee=None;notes.append("Cost-currency NOK conversion unavailable: "+fee_source)
                else:
                    fee*=rate
    status=("SAXO_COST_SCENARIO" if all(
        x is not None for x in (price,point_value,spread_bps,fee,min_trade,step)
    ) else "INCOMPLETE")
    if status!="SAXO_COST_SCENARIO":
        notes.append("Cannot use Saxo-calibrated replay without complete GET evidence")
    return SaxoReplayCostEvidenceV2(
        account_id=account_id,product_uic=instrument.uic,
        asset_type=instrument.asset_type,price_currency=currency or None,
        account_currency=str(account.get("currency") or ""),price=price,
        point_value_nok=point_value,fx_source=fxsource,
        spread_bps=spread_bps,fixed_commission_nok=fee,
        minimum_trade_size=min_trade,increment_size=step,status=status,
        notes=tuple(notes),
    )


def verified_replay_costs_v2(evidence:SaxoReplayCostEvidenceV2,*,
    max_lots:float=.03,starting_nav_nok:float=10000.)->ReplayCostsV2:
    if evidence.status!="SAXO_COST_SCENARIO":
        raise ValueError("Saxo cost scenario requires all verified broker details")
    assert evidence.point_value_nok is not None
    assert evidence.spread_bps is not None
    assert evidence.fixed_commission_nok is not None
    assert evidence.increment_size is not None
    return ReplayCostsV2(
        point_value_nok=evidence.point_value_nok,
        spread_bps=evidence.spread_bps,
        variable_fee_bps=0.,fixed_fee_nok=evidence.fixed_commission_nok,
        lot_step=evidence.increment_size,max_lots=max_lots,
        starting_nav_nok=starting_nav_nok,
        source=(f"SAXO_INDICATIVE_NOW account={evidence.account_id[-5:]} "
                f"uic={evidence.product_uic}/{evidence.asset_type}; "
                "current not historical spread/commission"),
    )


__all__=["SaxoReplayCostEvidenceV2","saxobank_accounts_v2",
         "saxo_replay_costs_v2","verified_replay_costs_v2"]
