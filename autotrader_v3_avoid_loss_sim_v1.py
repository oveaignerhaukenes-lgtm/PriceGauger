"""Avoid Loss V1 causal, costed account-NAV SIM on canonical 1m prices.

This is NOT a Saxo fill replay.  The supplied leverage, margin, commission,
spread, slippage and overnight carry are explicit scenario assumptions.
Candle HIGH/LOW path is unknowable: evaluate adverse threshold BEFORE favourable
new peak to avoid flattering intrabar lookahead; gap stops fill at next OPEN.

One tranche at most. Entries use only completed MACD-2m bars and historical
breakout ranges. User's performance objective: portfolio NAV after *all
modelled* costs, not gross trade P/L or percentage of underlying Tech100.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Sequence

from autotrader_v3_avoid_loss_v1 import (
    AvoidLossEntrySignalV1, AvoidLossReentryV1, evaluate_flat_entry_v1,
    LOSS_STOP_PCT, TRAIL_ACTIVATE_PCT, PEAK_GIVEBACK, _utc,
)


@dataclass(frozen=True)
class AvoidLossSimulationConfigV1:
    initial_nav_nok: float = 10000.0
    margin_per_trade_nok: float = 1000.0
    notional_per_trade_nok: float = 10000.0
    commission_bps_per_side: float = 1.0
    full_spread_bps: float = 1.0
    slippage_bps_per_side: float = 0.5
    daily_financing_bps: float = 1.0
    minimum_breakout_bars: int = 5

    def __post_init__(self):
        numbers=(self.initial_nav_nok,self.margin_per_trade_nok,
                 self.notional_per_trade_nok,self.commission_bps_per_side,
                 self.full_spread_bps,self.slippage_bps_per_side,
                 self.daily_financing_bps)
        if not all(isfinite(float(v)) for v in numbers):
            raise ValueError("SIM capital and costs must be finite")
        if (self.initial_nav_nok<=0 or self.margin_per_trade_nok<=0
            or self.notional_per_trade_nok<=0
            or self.margin_per_trade_nok>self.initial_nav_nok
            or any(v<0 for v in numbers[3:])):
            raise ValueError("invalid SIM account/margin/cost assumptions")
        if self.minimum_breakout_bars<3:
            raise ValueError("requires confirmed breakout lookback")


@dataclass(frozen=True)
class AvoidLossSimTradeV1:
    entry_at: datetime
    exit_at: datetime
    direction: int
    entry_price: float
    exit_price: float
    net_pnl_nok: float
    peak_pnl_nok: float
    reason: str
    margin_nok: float


@dataclass(frozen=True)
class AvoidLossSimResultV1:
    initial_nav_nok: float
    final_nav_nok: float
    net_pct: float
    gross_pnl_nok: float
    total_costs_nok: float
    max_drawdown_pct: float
    trades: tuple[AvoidLossSimTradeV1,...]
    equity: tuple[tuple[datetime,float],...]
    completed_minutes: int
    open_position_direction: int
    assumptions: AvoidLossSimulationConfigV1


def _ema(points,period):
    if len(points)<period:
        return [None]*len(points)
    values=[None]*len(points)
    ema=sum(points[:period])/period
    values[period-1]=ema
    alpha=2.0/(period+1)
    for i in range(period,len(points)):
        ema=alpha*points[i]+(1-alpha)*ema
        values[i]=ema
    return values


def _closed_macd_2m(bars):
    """No partial 2m candle, no gap filled by artificial equal-price candles."""
    grouped={}
    for bar in bars:
        t=bar[0]
        bucket=t-timedelta(minutes=t.minute%2,seconds=t.second,microseconds=t.microsecond)
        grouped.setdefault(bucket,[]).append(bar)
    completed=[]
    for t,group in sorted(grouped.items()):
        group.sort(key=lambda x:x[0])
        if len(group)!=2 or group[0][0]!=t or group[1][0]!=t+timedelta(minutes=1):
            continue
        completed.append((t+timedelta(minutes=2),group[-1][4]))
    close=[x[1] for x in completed]
    fast=_ema(close,12)
    slow=_ema(close,26)
    signal=[]
    macd=[]
    for f,s in zip(fast,slow):
        macd.append(None if f is None or s is None else f-s)
    nonnull=[x for x in macd if x is not None]
    macd_signal=_ema(nonnull,9)
    idx=0
    for i,m in enumerate(macd):
        if m is None:
            signal.append(None)
        else:
            sig=macd_signal[idx]
            signal.append(None if sig is None else m-sig)
            idx+=1
    return {t:h for (t,_),h in zip(completed,signal) if h is not None}


def _bars_1m(candles:Sequence):
    valid={}
    for item in candles:
        # CanonicalMarketBarV2.point exposes bar_time,open,high,low,close.
        b=getattr(item,"point",item)
        at=_utc(b.bar_time)
        if at.second or at.microsecond:
            continue
        op,hi,lo,cl=[float(getattr(b,x)) for x in ("open","high","low","close")]
        if not all(isfinite(v) and v>0 for v in (op,hi,lo,cl)):
            continue
        if lo>min(op,cl) or hi<max(op,cl):
            continue
        valid[at]=(at,op,hi,lo,cl)
    return [valid[k] for k in sorted(valid)]


def _execution_cost_nok(config):
    # A conservative fixed estimate per entry/exit leg. Round-trip spread is
    # charged as half-spread on each side, not once per leg.
    bps=(config.commission_bps_per_side+config.slippage_bps_per_side+
         config.full_spread_bps/2)
    return config.notional_per_trade_nok*bps/10000


def run_avoid_loss_sim_v1(
    canonical_bars: Sequence,
    *,
    config:AvoidLossSimulationConfigV1=AvoidLossSimulationConfigV1(),
    started_at:datetime|None=None,
) -> AvoidLossSimResultV1:
    bars=_bars_1m(canonical_bars)
    window_start=_utc(started_at) if started_at is not None else None
    if not bars:
        raise ValueError("no finished canonical 1m price candles")
    signals=_closed_macd_2m(bars)
    leg_cost=_execution_cost_nok(config)
    net_nav=float(config.initial_nav_nok)
    gross_sum=cost_sum=0.0
    position=0
    entry_price=entry_time=None
    net_at_entry=0.0
    top_net=0.0
    trailing=False
    cash_costs_so_far=0.0
    initial_margin=config.margin_per_trade_nok
    last_signal_at=None
    last_exit=None
    prev_signal=None
    prior_bar=None
    history=[]
    completed=[]
    high_water=float(config.initial_nav_nok)
    max_dd=0.0
    equity=[]
    last_t=None

    def pnl_at(price,when):
        if not position:
            return 0.0
        market=(price/entry_price-1.0)*config.notional_per_trade_nok*position
        age_days=max(0.0,(when-entry_time).total_seconds()/86400)
        carry=config.notional_per_trade_nok*config.daily_financing_bps/10000*age_days
        # include opening fee charged and projected closing fee; carrying cost
        return market-2*leg_cost-carry

    def close(price,when,reason):
        nonlocal net_nav,position,entry_price,entry_time,top_net
        nonlocal gross_sum,cost_sum,trailing,last_exit,cash_costs_so_far
        raw=(price/entry_price-1.0)*config.notional_per_trade_nok*position
        carry=config.notional_per_trade_nok*config.daily_financing_bps/10000*max(
            0.0,(when-entry_time).total_seconds()/86400)
        costs=2*leg_cost+carry
        gain=raw-costs
        gross_sum+=raw
        cost_sum+=costs
        net_nav+=gain
        completed.append(AvoidLossSimTradeV1(
            entry_at=entry_time,exit_at=when,direction=position,
            entry_price=entry_price,exit_price=price,
            net_pnl_nok=gain,peak_pnl_nok=top_net,
            reason=reason,margin_nok=initial_margin))
        last_exit=AvoidLossReentryV1(
            eligible_after=when,last_closed_direction=position)
        position=0
        entry_price=entry_time=None
        top_net=0.0
        trailing=False

    for bar in bars:
        t,op,hi,lo,cl=bar
        if window_start is not None and t<window_start:
            h=signals.get(t)
            if h is not None: prev_signal=(t,h)
            last_t=t
            history.append(bar)
            history=history[-max(30,config.minimum_breakout_bars*3):]
            continue
        if last_t is not None and t-last_t!=timedelta(minutes=1):
            # No invented missing candles; gap price is a real next OPEN.
            if position:
                gap_pnl=pnl_at(op,t)
                threshold=(-.01*initial_margin)
                limit=top_net*(1-PEAK_GIVEBACK) if trailing else None
                if gap_pnl<=threshold or (limit is not None and gap_pnl<=limit):
                    close(op,t,"GAP_STOP")
            history.clear()
            prev_signal=None
        last_t=t

        # Stops look at *this* minute's OPEN first, then adverse intrabar low/high.
        # No assumptions about favourable extremum being reached before adverse.
        if position:
            worst=lo if position==1 else hi
            best=hi if position==1 else lo
            at_open=pnl_at(op,t)
            threshold=LOSS_STOP_PCT/100*initial_margin
            protected=top_net*(1-PEAK_GIVEBACK) if trailing else None
            stop_reason=None
            execution=None
            if at_open<=threshold or (protected is not None and at_open<=protected):
                stop_reason="GAP_OR_OPEN_STOP"
                execution=op
            else:
                at_worst=pnl_at(worst,t)
                barrier=protected if protected is not None and protected>threshold else threshold
                if at_worst<=barrier:
                    # Solve the percentage-price barrier exactly with cost/carry.
                    age_days=(t-entry_time).total_seconds()/86400
                    cost=2*leg_cost+config.notional_per_trade_nok*config.daily_financing_bps/10000*age_days
                    price=entry_price*(1+position*(barrier+cost)/config.notional_per_trade_nok)
                    execution=max(worst,price) if position==1 else min(worst,price)
                    stop_reason="PEAK_GIVEBACK" if protected is not None and protected>=threshold else "LOSS_STOP"
            if stop_reason:
                close(execution,t,stop_reason)
            else:
                best_pnl=pnl_at(best,t)
                top_net=max(top_net,best_pnl)
                if top_net>=TRAIL_ACTIVATE_PCT/100*initial_margin:
                    trailing=True
                # With unknown intrabar path, we do NOT stop again based on a
                # floor established later within this same 1m candle.

        # All entries use a *previously completed* 2m MACD signal; no looking
        # at this minute's HIGH/LOW or CLOSE to decide an OPEN at its open.
        h=signals.get(t)
        if h is not None:
            if prev_signal is not None and prev_signal[0]==t-timedelta(minutes=2):
                prior_h=prev_signal[1]
                count=min(config.minimum_breakout_bars,len(history))
                # True previous candle extrema only, no current bar leakage.
                prev=history[-count:] if count else ()
                max_prev=max((x[2] for x in prev),default=float("inf"))
                min_prev=min((x[3] for x in prev),default=float("-inf"))
                direction=(1 if op>max_prev else -1 if op<min_prev else 0)
                # Estimate one average TRUE RANGE opportunity based only on
                # past completed 1m candles. No claim that it WILL occur.
                lookback=history[-max(5,config.minimum_breakout_bars):]
                avg_range=sum(x[2]-x[3] for x in lookback)/len(lookback) if lookback else 0.0
                opportunity=100*avg_range/max(op,1e-9)*config.notional_per_trade_nok/initial_margin
                cost_pct=100*(2*leg_cost)/initial_margin
                signal=AvoidLossEntrySignalV1(
                    confirmed_at=t,prior_histogram=prior_h,histogram=h,
                    breakout_direction=direction,expected_opportunity_pct=opportunity,
                    estimated_round_trip_cost_pct=cost_pct)
                if not position:
                    intended,_=evaluate_flat_entry_v1(
                        signal=signal,last_exit=last_exit,now=t)
                    if intended and net_nav>=initial_margin:
                        position=intended
                        entry_price=op
                        entry_time=t
                        top_net=-2*leg_cost
                        trailing=False
                        # A newly opened trade is also exposed to the adverse
                        # OHLC extreme of THIS FIRST minute. Never allow a
                        # freshly opened trade to bypass the 1% hard barrier
                        # until the next bar just because entries are filled
                        # at the current minute open.
                        worst=lo if position==1 else hi
                        barrier=LOSS_STOP_PCT/100*initial_margin
                        if pnl_at(worst,t)<=barrier:
                            open_loss=pnl_at(op,t)
                            if open_loss<=barrier:
                                execution=op
                            else:
                                execution=entry_price*(
                                    1+position*(barrier+2*leg_cost)/
                                    config.notional_per_trade_nok)
                                execution=(max(worst,execution) if position==1
                                           else min(worst,execution))
                            close(execution,t,"ENTRY_MINUTE_LOSS_STOP")
                # Do NOT automatically reverse existing exposure at MACD cross;
                # hold it until the position's own protective exit.
            prev_signal=(t,h)

        if position:
            # Mark to liquidate includes *both* sides and accrued carry.
            valuation=net_nav+pnl_at(cl,t)
        else:
            valuation=net_nav
        high_water=max(high_water,valuation)
        max_dd=max(max_dd,100*(1-valuation/high_water)) if high_water>0 else max_dd
        equity.append((t,round(valuation,6)))
        history.append(bar)
        history=history[-max(30,config.minimum_breakout_bars*3):]

    # Open-position P/L is included in terminal NAV, not silently ignored.
    final_nav=equity[-1][1]
    return AvoidLossSimResultV1(
        initial_nav_nok=config.initial_nav_nok,final_nav_nok=final_nav,
        net_pct=100*(final_nav/config.initial_nav_nok-1),
        gross_pnl_nok=gross_sum,
        total_costs_nok=cost_sum + (2*leg_cost if position else 0),
        max_drawdown_pct=max_dd,trades=tuple(completed),equity=tuple(equity),
        completed_minutes=len(equity),open_position_direction=position,
        assumptions=config,
    )


__all__=["AvoidLossSimulationConfigV1","AvoidLossSimTradeV1",
         "AvoidLossSimResultV1","run_avoid_loss_sim_v1","_closed_macd_2m"]
