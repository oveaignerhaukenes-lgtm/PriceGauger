"""Strict Saxo evidence adapter for Avoid Loss V1 (no HTTP or order capability).

For live use, the calling worker must have independently established that:
  * exact Saxo account boundary matches the row,
  * the view's BaseCurrency is the SAME NOK account currency (not group USD),
  * frozen margin is from the opening order's actual precheck, attached only
    after Saxo confirms its fill, and retired on any quantity/identity change.

Do not infer NOK from a missing field, or use ProfitLossOnTrade (instrument
currency), account notional, current index price, or current margin.
"""
from __future__ import annotations

from datetime import datetime
from math import isfinite

from autotrader_v3_avoid_loss_v1 import (
    BrokerPnLSampleV1, ConfirmedPositionV1, _finite, _utc,
)


def precheck_margin_nok_v1(precheck: dict, *, side: str,
                           account_currency: str = "NOK") -> float:
    """Get the proposed first-position margin *before* actual Saxo fill.

    This figure may become an immutable risk denominator only after the
    matching reserved request reconciles to a confirmed broker position.
    """
    if not isinstance(precheck,dict):
        raise ValueError("Saxo precheck is unavailable")
    if str(precheck.get("PreCheckResult") or precheck.get("Result") or "").lower() not in {
        "ok","passed","success"
    }:
        raise ValueError("Saxo precheck was not approved")
    if account_currency!="NOK" or side not in {"Buy","Sell"}:
        raise ValueError("exact NOK account and Buy/Sell are required")
    margin = precheck.get("MarginImpactBuySell")
    if not isinstance(margin,dict) or margin.get("Currency")!="NOK":
        raise ValueError("Saxo margin currency missing or not NOK")
    amount = _finite(margin.get("InitialMarginBuy" if side=="Buy" else "InitialMarginSell"),
                     name="initial Saxo margin")
    if amount<=0:
        raise ValueError("Saxo margin must be positive")
    return amount


def validated_saxo_pnl_v1(
    *,
    row: dict,
    position: ConfirmedPositionV1,
    account_currency: str,
    verified_base_currency: str,
    estimated_exit_cost_nok: float,
    received_at: datetime,
) -> BrokerPnLSampleV1:
    """Read only genuine base-currency trade P/L, known costs and quote clock.

    TradeCostsTotalInBaseCurrency represents opening and projected closing
    costs according to Saxo. The estimated extra exit costs argument must
    contain only costs NOT ALREADY INCLUDED by Saxo; callers must prove this
    independently, to avoid counting the same commission twice.
    """
    _utc(received_at)
    if account_currency!="NOK" or verified_base_currency!="NOK":
        raise ValueError("account/base currency must both be independently confirmed NOK")
    if not isinstance(row,dict):
        raise ValueError("Saxo net position row is missing")
    base = row.get("NetPositionBase")
    view = row.get("NetPositionView")
    if not isinstance(base,dict) or not isinstance(view,dict):
        raise ValueError("exact Saxo position view required")
    returned_account=str(base.get("PositionsAccount") or base.get("AccountId") or "")
    if returned_account != position.account_id:
        raise ValueError("Saxo account boundary mismatch")
    if int(base.get("Uic") or -1)!=position.uic or str(base.get("AssetType") or "")!=position.asset_type:
        raise ValueError("Saxo product boundary mismatch")
    if str(row.get("NetPositionId") or "")!=position.position_token:
        raise ValueError("Saxo position lifecycle mismatch")
    long_amt = _finite(base.get("AmountLong") or 0.0,name="amount long")
    short_amt = _finite(base.get("AmountShort") or 0.0,name="amount short")
    if not isfinite(long_amt-short_amt) or abs((long_amt-short_amt)-position.signed_amount)>1e-9:
        raise ValueError("Saxo amount mismatch: margin denominator not reusable")
    if str(view.get("Status") or "Open").lower() not in {"open","partiallyclosed"}:
        raise ValueError("position is already closing or closed")
    raw_trade_pnl=view.get("ProfitLossOnTradeInBaseCurrency")
    raw_costs=view.get("TradeCostsTotalInBaseCurrency")
    if raw_trade_pnl is None or raw_costs is None:
        raise ValueError("missing Saxo P/L or cost figure in account currency")
    if "CurrentPriceDelayMinutes" not in view or "CalculationReliability" not in view:
        raise ValueError("quote-delay/reliability evidence missing")
    pnl=_finite(raw_trade_pnl,name="trade P/L in NOK")
    costs=_finite(raw_costs,name="known Saxo costs in NOK")
    extra=_finite(estimated_exit_cost_nok,name="additional exit costs")
    if costs<0 or extra<0:
        raise ValueError("costs cannot be negative")
    raw_at=view.get("CurrentPriceLastTraded")
    if not isinstance(raw_at,str) or not raw_at.strip():
        raise ValueError("exact quote timestamp missing")
    quoted_at=datetime.fromisoformat(raw_at.replace("Z","+00:00"))
    quoted_at=_utc(quoted_at)
    lag = int(view.get("CurrentPriceDelayMinutes"))
    return BrokerPnLSampleV1(
        position_key=position.key,
        mark_to_liquidate_nok=pnl-costs-extra,
        currency="NOK",
        as_of=quoted_at,
        reliability=str(view["CalculationReliability"]),
        quote_delay_minutes=lag,
        has_verified_costs=True,
    )


__all__=["precheck_margin_nok_v1","validated_saxo_pnl_v1"]
