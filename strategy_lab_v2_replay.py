"""Strategy Lab v2: an isolated, causal replay of genuine pure V3 strategy rules.

This module NEVER calls the stateful V3 closed-bar driver or production SQL.
It consumes exact subscribed Saxo 1m OHLC, computes closed-bar MACD from
contiguous segments, fills a prior-bar target only on NEXT 1m open, and
charges explicit research-cost assumptions. This is PAPER, not Saxo fills.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime,timedelta,timezone
from math import isfinite
from typing import Sequence
from collections import defaultdict

from autotrader_v3_registry_v1 import STRATEGIES_V3,TIMEFRAMES_V3
from autotrader_v3_domain import TargetInventoryV3
from autotrader_mtf_entry_shadow_v2 import macd_observations_v2
from trading_desk import ChartBar
from autotrader_v3_macd_flip_v1 import macd_flip_target_v3
from autotrader_v3_macd_histogram_v1 import MacdHistogramConfigV3,macd_histogram_target_v3
from autotrader_v3_macd_trailing_v1 import MacdTrailingConfigV3,macd_trailing_target_v3
from autotrader_v3_macd_histogram_flip_build_v1 import macd_histogram_flip_build_target_v3
from autotrader_v3_macd_histogram_peak_flip_v1 import (
    HistogramPeakStateV3,histogram_peak_flip_transition_v3,
)
from autotrader_v3_macd_stoch_v2 import macd_stoch_v2_target_v3
from autotrader_v3_macd_stoch_v21 import macd_stoch_v21_target_v3
from autotrader_v3_macd_stoch_rhythm_build_v1 import macd_stoch_rhythm_build_target_v3
from autotrader_v3_precross_price_v1 import precross_price_target_v3,histogram_price_target_v3

PURE_V3={
    "macd-flip":macd_flip_target_v3,
    "macd":macd_trailing_target_v3,
    "macd-histogram":macd_histogram_target_v3,
    "macd-histogram-flip-build":macd_histogram_flip_build_target_v3,
    "macd-histogram-peak-flip":histogram_peak_flip_transition_v3,
    "macd-stoch-v2":macd_stoch_v2_target_v3,
    "macd-stoch-v2-1":macd_stoch_v21_target_v3,
    "macd-stoch-rhythm-build":macd_stoch_rhythm_build_target_v3,
    "precross-price-1m-macd2m":precross_price_target_v3,
    "histogram-price-1m-macd2m":histogram_price_target_v3,
}
PRECROSS=frozenset(("precross-price-1m-macd2m","histogram-price-1m-macd2m"))
TRAILING=frozenset(("macd-flip","macd","macd-stoch-v2","macd-stoch-v2-1","macd-stoch-rhythm-build"))
PERIODS={"1m":1,"2m":2,"5m":5,"10m":10,"15m":15,"30m":30,"1h":60}
MIN_HISTORY=45
MAX_BARS=3000


def utc(raw)->datetime:
    val=raw if isinstance(raw,datetime) else datetime.fromisoformat(str(raw).replace("Z","+00:00"))
    if val.tzinfo is None:
        raise ValueError("replay requires timestamp with timezone")
    return val.astimezone(timezone.utc)


def strategy_family_v2(key:str)->str:
    k=str(key)
    if k.startswith("aen-") or k.startswith("aen2") or k.startswith("aen21"):
        return "AEn / adaptive"
    if "precross" in k or "price" in k or "fraktal" in k:
        return "Pris / fraktal"
    if "stoch" in k or "rhythm" in k:
        return "Stochastic / rytme"
    if "histogram" in k or "regime" in k:
        return "MACD histogram / regime"
    if "macd" in k:
        return "MACD basis"
    return "Andre / forskningsstrategier"


def strategy_catalog_v2()->dict[str,tuple]:
    result=defaultdict(list)
    for entry in STRATEGIES_V3:
        result[strategy_family_v2(entry.key)].append({
            "key":entry.key,"name":entry.label,"description":entry.description,
            "replay_ready":entry.key in PURE_V3,
            "runtime_ready":entry.runtime_ready,
            "ai_capable":False,  # AI manager is an external overlay, not an LLM strategy.
        })
    return {key:tuple(result[key]) for key in sorted(result)}


@dataclass(frozen=True,slots=True)
class ReplayCostsV2:
    """Research inputs; never represent as archived broker costs."""
    point_value_nok:float
    spread_bps:float
    variable_fee_bps:float
    fixed_fee_nok:float
    lot_step:float=.01
    max_lots:float=.03
    starting_nav_nok:float=10000.
    source:str="MANUAL_SCENARIO"

    def __post_init__(self):
        for name in ("point_value_nok","lot_step","max_lots","starting_nav_nok"):
            v=float(getattr(self,name))
            if not isfinite(v) or v<=0:raise ValueError(f"{name} must be positive")
        for name in ("spread_bps","variable_fee_bps","fixed_fee_nok"):
            v=float(getattr(self,name))
            if not isfinite(v) or v<0:raise ValueError(f"{name} must be nonnegative")
        if self.max_lots<self.lot_step:
            raise ValueError("max_lots < lot_step")


@dataclass(frozen=True,slots=True)
class ReplayEventV2:
    at:datetime
    strategy:str
    kind:str
    prior_lots:float
    after_lots:float
    price:float
    cost_nok:float
    reason:str


@dataclass(frozen=True,slots=True)
class ReplayPointV2:
    at:datetime
    price:float
    nav_nok:float
    lots:float
    macd_hist:float|None
    signal:str


@dataclass(frozen=True,slots=True)
class ReplayResultV2:
    strategy:str
    points:tuple[ReplayPointV2,...]
    events:tuple[ReplayEventV2,...]
    total_cost_nok:float
    trades:int
    drawdown_pct:float
    net_return_pct:float
    skipped_gaps:int
    cost_source:str


def _segments(bars):
    """Reject duplicate and malformed source data; gaps reset indicator state."""
    ordered=sorted(bars,key=lambda b:utc(b.bar_time))
    if len(ordered)>MAX_BARS:
        raise ValueError(f"replay limited to {MAX_BARS} historical 1m bars")
    result=[]; segment=[];prev=None
    for bar in ordered:
        t=utc(bar.bar_time)
        values=(float(bar.open),float(bar.high),float(bar.low),float(bar.close))
        if (t.second or t.microsecond or not all(isfinite(x) and x>0 for x in values)
            or values[2]>min(values[0],values[3])
            or values[1]<max(values[0],values[3])):
            raise ValueError("invalid canonical OHLC source")
        if prev and t<=prev:raise ValueError("duplicate/out-of-order canonical 1m time")
        if prev and t-prev!=timedelta(minutes=1):
            if segment:result.append(tuple(segment))
            segment=[]
        segment.append(bar);prev=t
    if segment:result.append(tuple(segment))
    return tuple(result)


def _complete_candles(segment,minutes,market):
    buckets=defaultdict(list)
    for b in segment:
        start=utc(b.bar_time)
        epoch=int(start.timestamp())
        aligned=datetime.fromtimestamp(epoch-epoch%(60*minutes),tz=timezone.utc)
        buckets[aligned].append(b)
    out=[]
    for start in sorted(buckets):
        group=buckets[start]
        if len(group)!=minutes or utc(group[0].bar_time)!=start:
            continue
        if utc(group[-1].bar_time)!=start+timedelta(minutes=minutes-1):
            continue
        out.append(ChartBar(
            market=market,bar_time=start,open=float(group[0].open),
            high=max(float(x.high) for x in group),
            low=min(float(x.low) for x in group),
            close=float(group[-1].close),
            volume=(sum(float(x.volume) for x in group)
                    if all(x.volume is not None for x in group) else None),
        ))
    return tuple(out)


def _call_strategy(key,target,obs,prev,bars,source,peak_state,config,market):
    func=PURE_V3[key]
    args=dict(current_target=TargetInventoryV3(target),observation=obs,
              previous_observation=prev,config=config)
    if key=="macd-histogram-peak-flip":
        result=func(**args,state=peak_state)
        return result.decision,result.state
    if key in PRECROSS:
        args.update(bars=bars,source_bars=source,market_name=market)
    elif key in {"macd-stoch-v2","macd-stoch-v2-1","macd-stoch-rhythm-build"}:
        args["bars"]=bars
    return func(**args),peak_state


def replay_v3_strategy_v2(*,strategy_key:str,bars:Sequence,costs:ReplayCostsV2,
                          timeframe:str="2m")->ReplayResultV2:
    """Full replay, no SQL. An order from candle T fills at T+1m OPEN only.

    A reversal first closes at the next open. Re-entry cannot fill before a
    subsequent observed minute. If a canonical gap occurs, positions are
    flattened at the last verified close with explicit cost, and pending
    intent is cancelled (no fictitious cross-gap profit).
    """
    if strategy_key not in PURE_V3:
        raise ValueError(f"Strategy not yet replay-ready: {strategy_key}")
    if timeframe not in PERIODS:
        raise ValueError("unsupported signal timeframe")
    if strategy_key in PRECROSS and timeframe!="1m":
        raise ValueError("1m price + 2m MACD strategies require 1m signal")
    if strategy_key=="macd-stoch-rhythm-build" and timeframe!="1m":
        raise ValueError("Rhythm build requires 1m")
    segments=_segments(bars)
    if sum(len(x) for x in segments)<MIN_HISTORY:
        raise ValueError("Not enough real 1m candles for technical warmup")
    nav=float(costs.starting_nav_nok)
    position=0.;peak=nav;dd=0.;spent=0.;trades=0;gaps=0
    events=[];points=[]
    market=str(segments[0][0].market_name)
    max_lots=float(costs.max_lots)
    config=(MacdTrailingConfigV3(tranche=costs.lot_step,max_inventory=max_lots)
            if strategy_key in TRAILING else
            MacdHistogramConfigV3(tranche=costs.lot_step,max_inventory=max_lots))
    for index,segment in enumerate(segments):
        if index and position:
            prev_close=float(segments[index-1][-1].close)
            charge=abs(position)*prev_close*costs.point_value_nok*(
                costs.spread_bps/20000+costs.variable_fee_bps/10000
            )+costs.fixed_fee_nok
            nav-=charge;spent+=charge;trades+=1
            events.append(ReplayEventV2(
                utc(segments[index-1][-1].bar_time)+timedelta(minutes=1),
                strategy_key,"GAP_FLAT",position,0.,prev_close,charge,
                "Discontinuity in real 1m bars; flatten at last known close",
            ))
            position=0.
        if index:gaps+=1
        tf=PERIODS[timeframe]
        macd_tf=2 if strategy_key in PRECROSS else tf
        chart=_complete_candles(segment,macd_tf,market)
        observations=macd_observations_v2(chart,timeframe_minutes=macd_tf) if len(chart)>=34 else ()
        by_end={utc(x.closed_at):x for x in observations}
        signal_chart=_complete_candles(segment,tf,market) if tf!=macd_tf else chart
        signal_by_end={utc(x.bar_time)+timedelta(minutes=tf):j
                       for j,x in enumerate(signal_chart)}
        previous_obs=None;pending=None
        most_recent=None
        target=0.;peak_state=HistogramPeakStateV3()
        last_close=None
        for ix,bar in enumerate(segment):
            opened=utc(bar.bar_time); closed=opened+timedelta(minutes=1)
            op=float(bar.open);cl=float(bar.close)
            if last_close is not None:
                nav+=position*(op-last_close)*costs.point_value_nok
            # Process a prior CLOSE-bar request only now at the NEXT observed OPEN.
            if pending is not None:
                wanted=float(pending[0])
                wanted=round(max(-max_lots,min(max_lots,wanted))/costs.lot_step)*costs.lot_step
                wanted=round(wanted,10)
                # Never net-cross opposite sides at a single fake fill.
                if wanted*position<0:
                    actual_next=0.
                else:
                    actual_next=wanted
                if abs(actual_next-position)>1e-9:
                    delta=abs(actual_next-position)
                    charge=delta*op*costs.point_value_nok*(
                        costs.spread_bps/20000+costs.variable_fee_bps/10000
                    )+costs.fixed_fee_nok
                    before=position
                    nav-=charge;spent+=charge;trades+=1
                    position=actual_next
                    events.append(ReplayEventV2(
                        opened,strategy_key,
                        "CLOSE" if not position else "OPEN" if not before
                        else "ADD" if abs(position)>abs(before) else "REDUCE",
                        before,position,op,charge,str(pending[1])[:500],
                    ))
                    if wanted*before<0:
                        # Subsequent leg of a flat-first reversal waits again.
                        pending=(wanted,pending[1])
                    else:pending=None
                else:pending=None
            nav+=position*(cl-op)*costs.point_value_nok
            if nav<0:
                raise ValueError("paper NAV exhausted; exposure/capital unrealistic")
            last_close=cl
            if closed in by_end:
                most_recent=by_end[closed]
            sig="WARMUP"
            if most_recent and (closed in signal_by_end):
                obs=most_recent if strategy_key in PRECROSS else by_end.get(closed)
                if obs is not None:
                    end_i=signal_by_end[closed]+1
                    visible=signal_chart[max(0,end_i-130):end_i]
                    source=segment[max(0,ix-420):ix+1]
                    # Price strategies check last 5 contiguous source bars,
                    # and the only 2m observation available at this minute.
                    args_bars=(tuple(segment[max(0,ix-130):ix+1])
                               if strategy_key in PRECROSS else visible)
                    decision,peak_state=_call_strategy(
                        strategy_key,target,obs,previous_obs,args_bars,source,
                        peak_state,config,market)
                    target=max(-max_lots,min(max_lots,float(decision.target.amount)))
                    sig=str(decision.action)
                    if abs(target-position)>1e-9:
                        pending=(target,decision.reason)
                    else:pending=None
                    previous_obs=obs
            peak=max(peak,nav)
            dd=max(dd,(peak-nav)/peak*100)
            points.append(ReplayPointV2(
                closed,cl,nav,position,
                float(most_recent.spread) if most_recent else None,sig,
            ))
        # Don't carry a pending order or indicators across a data gap.
    return ReplayResultV2(strategy_key,tuple(points),tuple(events),spent,
                          trades,dd,100*(nav/costs.starting_nav_nok-1),
                          gaps,costs.source)


__all__=["ReplayCostsV2","ReplayEventV2","ReplayPointV2","ReplayResultV2",
         "PURE_V3","strategy_catalog_v2","strategy_family_v2",
         "replay_v3_strategy_v2"]
