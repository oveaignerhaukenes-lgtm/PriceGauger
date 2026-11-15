"""Versioned, price-confirmed exit of MACD-Stoch V2.1 one-sided R/E.

V1 is intentionally unchanged. MACD E is an *exit warning* for already
owned positions; observed, fully closed 1m price action must confirm a
normal exit. A very large closed-bar adverse breakdown can exit directly.
The separately selectable 10s LIVE Impulse Exit remains an independent
protective modifier (not part of this bar-level algorithm).

No synthetic intra-bar trade, no future prices, no broker calls or limits.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from math import isfinite
from statistics import mean

from autotrader_v3_domain import TargetInventoryV3
from autotrader_v3_macd_stoch_v21 import macd_stoch_v21_target_v3
from autotrader_v3_macd_trailing_v1 import MacdTrailingConfigV3
from autotrader_v3_macd_stoch_v21_split_v1 import (
    _completed_bars,_latest_macd,_utc,_decision,ALLOWED_CLOCKS_V3,SPLIT_KEYS_V3,
)

LONG_KEY_V2="macd-stoch-v21-r-long-flat-v2"
SHORT_KEY_V2="macd-stoch-v21-r-short-flat-v2"
SPLIT_V2_KEYS_V3=frozenset({LONG_KEY_V2,SHORT_KEY_V2})
ALL_SPLIT_KEYS_V3=frozenset(SPLIT_KEYS_V3 | SPLIT_V2_KEYS_V3)


@dataclass(frozen=True, slots=True)
class PriceExitEvidenceV2:
    atr_points: float
    signed_2m_change: float
    adverse_candles_3m: int
    structure_broken: bool
    severe_adverse_bar: bool
    sustained_adverse: bool


def price_exit_evidence_v2(*,source_bars,cutoff,market_name,side:int)->PriceExitEvidenceV2|None:
    """Last 18 contiguous and complete minutes, ATR computed before the signal.

    ATR and prior 3-bar structure are frozen at the previous completed bar;
    the candidate reversal cannot enlarge its own volatility tolerance.
    """
    bars=_completed_bars(source_bars,timeframe=1,cutoff=cutoff,market=market_name)
    if len(bars)<18:
        return None
    recent=bars[-18:]
    if any(_utc(b.bar_time)-_utc(a.bar_time)!=timedelta(minutes=1)
           for a,b in zip(recent,recent[1:])):
        return None
    # 14 true ranges ending at the bar BEFORE the current signal.
    tr=[]
    for prev,b in zip(recent[-16:-2],recent[-15:-1]):
        tr.append(max(b.high-b.low,abs(b.high-prev.close),abs(b.low-prev.close)))
    if len(tr)!=14 or not all(isfinite(x) and x>0 for x in tr):
        return None
    atr=mean(tr)
    now,previous,two_back=recent[-1],recent[-2],recent[-3]
    signed2=side*(now.close-two_back.close)
    signed1=side*(now.close-previous.close)
    # Close-to-close direction is more trustworthy than candle body color:
    # a green candle may still close BELOW the previous green candle.
    adverse=sum(side*(b.close-a.close)<0
                for a,b in zip(recent[-4:-1],recent[-3:]))
    if side>0:
        broken=now.close < min(x.low for x in recent[-4:-1]) - .10*atr
    else:
        broken=now.close > max(x.high for x in recent[-4:-1]) + .10*atr
    return PriceExitEvidenceV2(
        atr_points=atr,signed_2m_change=signed2,
        adverse_candles_3m=adverse,structure_broken=broken,
        severe_adverse_bar=signed1<=-1.50*atr,
        sustained_adverse=(adverse>=2 and signed2<=-.50*atr),
    )


def split_price_exit_v2(*,side:int,current_target:TargetInventoryV3,observation,
        previous_observation=None,bars=(),source_bars=(),
        regime_timeframe_minutes:int=15,exit_timeframe_minutes:int=2,
        market_name:str="",config:MacdTrailingConfigV3=MacdTrailingConfigV3()):
    if side not in (-1,1):
        raise ValueError("V2 side must be +1 or -1")
    if (int(regime_timeframe_minutes) not in ALLOWED_CLOCKS_V3 or
            int(exit_timeframe_minutes) not in ALLOWED_CLOCKS_V3):
        raise ValueError("Unsupported completed MACD clock")
    cutoff=getattr(observation,"closed_at",observation.bar_time)
    current=float(current_target.amount)
    if side*current < -1e-9:
        return _decision(amount=0,action="WRONG_SIDE_FLAT",reason="Opposite inventory denied",
                         observation=observation)
    regime=_latest_macd(source_bars,minutes=int(regime_timeframe_minutes),
                        cutoff=cutoff,market=market_name)
    exit_macd=_latest_macd(source_bars,minutes=int(exit_timeframe_minutes),
                           cutoff=cutoff,market=market_name)
    evidence=price_exit_evidence_v2(source_bars=source_bars,cutoff=cutoff,
                                    market_name=market_name,side=side)
    # Genuine complete prices are required even when MACD streams exist.
    if regime is None or exit_macd is None or evidence is None:
        return _decision(amount=0,action="CLOCK_OR_PRICE_UNAVAILABLE_FLAT",
                         reason="No fresh complete R/E clocks or contiguous 1m price/ATR",
                         observation=observation)
    if side*regime<=0:
        return _decision(amount=0,action="REGIME_FLAT",
                         reason=f"R{regime_timeframe_minutes} disallows side {side:+d}",
                         observation=observation)

    if current:
        # A violent observed price breakdown can invalidate the position even
        # before the 2m oscillator crosses. The optional 10s Impulse Exit is
        # faster still, but must not be emulated with an unclosed 1m candle.
        if evidence.severe_adverse_bar and evidence.structure_broken:
            return _decision(amount=0,action="PRICE_SHOCK_FLAT",
                             reason=f"1m structural shock, prior ATR={evidence.atr_points:.2f}",
                             observation=observation)
        if side*exit_macd<=0 and (
                evidence.sustained_adverse or evidence.structure_broken):
            return _decision(amount=0,action="PRICE_CONFIRMED_EXIT_FLAT",
                             reason=(f"E{exit_timeframe_minutes} counter-MACD AND adverse "
                                     f"price, signed2m={evidence.signed_2m_change:.2f}, "
                                     f"ATR={evidence.atr_points:.2f}"),observation=observation)

    base=macd_stoch_v21_target_v3(
        current_target=TargetInventoryV3(current),
        observation=observation,previous_observation=previous_observation,
        bars=bars,config=config,
    )
    proposed=float(base.target.amount)
    if proposed*side < -1e-9:
        return _decision(amount=current,action="WAIT_ALLOWED_SIDE",
                         reason="V2.1 opposite entry forbidden",observation=observation,base=base)
    if current and proposed==0.:
        return _decision(amount=current,action="HOLD_PRICE_UNCONFIRMED",
                         reason="Entry-clock flat ignored without observed adverse price",
                         observation=observation,base=base)
    if not current and side*exit_macd<=0:
        return _decision(amount=0,action="WAIT_EXIT_MACD_FOR_ENTRY",
                         reason="E clock against new opening; price-confirmed exits only for held inventory",
                         observation=observation,base=base)
    if proposed*side > current*side+1e-9:
        if side*exit_macd<=0:
            return _decision(amount=current,action="WAIT_EXIT_MACD_FOR_BUILD",
                             reason="Hold existing exposure, but never add against E MACD",
                             observation=observation,base=base)
        if evidence.sustained_adverse or evidence.structure_broken:
            return _decision(amount=current,action="WAIT_PRICE_ADVERSE",
                             reason="Recent complete prices oppose entry/build",
                             observation=observation,base=base)
        return _decision(amount=proposed,action=base.action,
                         reason=base.reason+"; R/E and price-confirmed V2",observation=observation,base=base)
    return _decision(amount=current,action="HOLD",
                     reason="V2.1 entry; E exit confirmed by closed 1m prices",observation=observation,base=base)


def long_flat_target_v2(**kwargs):
    return split_price_exit_v2(side=1,**kwargs)


def short_flat_target_v2(**kwargs):
    return split_price_exit_v2(side=-1,**kwargs)
