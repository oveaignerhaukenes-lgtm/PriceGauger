"""Avoid Loss V1: MACD-2m research entry target, exit owned by broker-P/L watchdog.

One legal Saxo tranche, no pyramid and no direct flips. The strategy
cannot infer whether 1% margin P/L has been reached from MACD/price alone.
That requires the separately validated NOK-account Saxo position watcher.
"""
from __future__ import annotations
from math import isfinite

from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_trailing_v1 import (
    MacdTrailingDecisionV3,MacdTrailingConfigV3,
)

STRATEGY_KEY_V3="avoid-loss-v1"


def avoid_loss_macd_entry_v1(*,current_target,observation,
                              previous_observation=None,bars=(),
                              config:MacdTrailingConfigV3=MacdTrailingConfigV3()):
    """Enter on a *fresh* MACD 2m cross or momentum+price breakout only.

    Typical bar range is an observable noise proxy, not a guarantee of
    future movement or a substitute for verified Saxo transaction economics.
    LIVE separately checks the Saxo broker cost/capital policy before OPEN.
    """
    signed=float(current_target.amount)
    spread=float(observation.spread)
    existing=TargetInventoryV3(signed)
    if signed:
        return MacdTrailingDecisionV3(existing,"HOLD_UNTIL_MARGIN_STOP",
            "Risk observer, not the MACD entry signal, owns -1/+2/10% exit",spread)
    if previous_observation is None or len(bars)<12:
        return MacdTrailingDecisionV3(existing,"HOLD_BOOTSTRAP",
            "Await two completed MACD 2m observations and prior price range",spread)
    historical=tuple(bars)
    prior=historical[-11:-1]
    if len(prior)!=10 or not all(
        isfinite(float(getattr(b,k,0))) for b in prior for k in ("high","low","close")
    ):
        return MacdTrailingDecisionV3(existing,"HOLD_NO_VALID_RANGE",
            "Missing price/noise history: remain FLAT",spread)
    last=historical[-1]
    last_close=float(last.close)
    if not isfinite(last_close) or last_close<=0:
        return MacdTrailingDecisionV3(existing,"HOLD_INVALID_PRICE",
            "No positive latest completed price",spread)
    mean_range=sum(max(0.0,float(b.high)-float(b.low)) for b in prior)/10
    # Price must have moved enough over the last ten completed bars for a
    # minimum viable range. Costs and actual leverage checked at Saxo gate.
    if mean_range/last_close<0.0003:
        return MacdTrailingDecisionV3(existing,"FLAT_TOO_LITTLE_MOVEMENT",
            "10-bar price range under 3bps; remain flat in noise",spread)
    prev=float(previous_observation.spread)
    cross_long=prev<=0<spread
    cross_short=prev>=0>spread
    max_high=max(float(b.high) for b in prior[-5:])
    min_low=min(float(b.low) for b in prior[-5:])
    growing_long=prev>0 and spread>prev and last_close>max_high
    growing_short=prev<0 and spread<prev and last_close<min_low
    direction=(1 if cross_long or growing_long else
               -1 if cross_short or growing_short else 0)
    if direction==0:
        return MacdTrailingDecisionV3(existing,"FLAT_NO_FRESH_EDGE",
            "No newly confirmed MACD cross or directionally matching breakout",
            spread)
    amount=float(config.tranche)*direction
    if abs(amount)>float(config.max_inventory)+1e-9:
        raise ValueError("Avoid Loss requested illegal Saxo inventory")
    target=TargetInventoryV3(amount)
    return MacdTrailingDecisionV3(target,
          "OPEN_MACD_CROSS" if cross_long or cross_short else "OPEN_HISTOGRAM_BREAKOUT",
          "One legal Saxo unit; 2m completed MACD with price-noise gate; "
          "risk stops use frozen broker margin, not underlying price",
          spread)


__all__=["STRATEGY_KEY_V3","avoid_loss_macd_entry_v1"]
