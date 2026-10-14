"""Research-only signal inversion experiment on canonical completed 1m bars.

Each ordinary/inverted pair reuses EXACTLY the same decision timestamps,
entry delays, time in market and absolute traded exposure. Random controls
draw new directions per holding interval but pay the *same original schedule*
turnover. This is deliberately a FIXED-TURNOVER placebo, not an executable
random trade strategy. No broker imports, live settings or account access.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from math import isfinite
from random import Random
from statistics import median
from types import SimpleNamespace
from typing import Sequence

from autotrader_v3_macd_histogram_peak_flip_v1 import (
    histogram_peak_flip_transition_v3, HistogramPeakStateV3,
)
from autotrader_v3_macd_histogram_v1 import MacdHistogramConfigV3
from autotrader_v3_domain import TargetInventoryV3
from macd_nextgen_paper_v1 import _observations, _utc

INVERSION_VERSION="lab-inversion-v1"
DEFAULT_RANDOM_CONTROLS=30
PERMITTED_MINUTES=(5,15)


@dataclass(frozen=True)
class InversionResult:
    model: str
    minutes: int
    variant: str
    net_pct: float
    gross_pct: float
    cost_pct: float
    max_dd_pct: float
    target_switches: int
    traded_legs: int
    participation_bars: int
    points: tuple[tuple[str,float], ...]


@dataclass(frozen=True)
class InversionExperiment:
    version: str
    start: str
    end: str
    completed_bars: int
    notional_fraction: float
    cost_per_leg_bps: float
    rows: tuple[InversionResult, ...]
    placebo_medians: tuple[tuple[str,int,float,float,float], ...]


def _signal_target_events(bars: Sequence, minutes: int, model: str):
    """MACD from real complete buckets; no signal before its timeframe close."""
    if minutes not in PERMITTED_MINUTES or model not in ("MACD Flip","Histogram Peak Flip"):
        raise ValueError("unsupported inversion model")
    observed=_observations(bars,minutes)
    target=0
    phase=HistogramPeakStateV3()
    previous=None
    last_time=None
    events=[]
    policy=MacdHistogramConfigV3(tranche=.01,max_inventory=.01)
    for end,obs in sorted(observed.items()):
        # Session gaps cannot manufacture confirmed MACD crosses or preserve
        # Peak Flip thresholds from an old disjoint trading session.
        contiguous=last_time is not None and end-last_time==timedelta(minutes=minutes)
        prior=previous if contiguous else None
        if not contiguous:
            phase=HistogramPeakStateV3()
        if prior is not None and model=="MACD Flip":
            a,b=float(prior.spread),float(obs.spread)
            if a<=0<b:target=1
            elif a>=0>b:target=-1
        elif model=="Histogram Peak Flip":
            step=histogram_peak_flip_transition_v3(
                current_target=TargetInventoryV3(target*.01),
                observation=obs,previous_observation=prior,
                state=phase,config=policy)
            phase=step.state
            target=1 if step.decision.target.amount>0 else (
                -1 if step.decision.target.amount<0 else 0)
        if not events or events[-1][1]!=target:
            events.append((end,target))
        previous,last_time=obs,end
    return tuple(events)


def _research_bars(bars: Sequence, *, started_at, ended_at):
    """Validated unique completed canonical 1m prices; preserve true gaps."""
    start,end=map(_utc,(started_at,ended_at))
    valid={}
    for b in bars:
        time=_utc(b.bar_time)
        if time>=end or time.second or time.microsecond:
            continue
        o,h,l,c=map(float,(b.open,b.high,b.low,b.close))
        if min(o,h,l,c)<=0 or not all(isfinite(x) for x in (o,h,l,c)):
            continue
        if not(l<=o<=h and l<=c<=h):
            continue
        valid[time]=SimpleNamespace(bar_time=time,open=o,high=h,low=l,close=c,
            market_name=str(getattr(b,"market_name","Instrument")))
    return tuple(valid[t] for t in sorted(valid)),start,end


def _score(bars, events, *, start, end, notional, cost_bps, mode, seed=0):
    """Identical 1m fill clock; next available 1m OPEN, including true price gaps.

    At a delayed open, only the LAST actionable signal is used. This models
    an ideal net reverse at one 1m-open rather than claiming Saxo would execute
    a CLOSE/CONFIRM_FLAT/OPEN instantaneously. The model is symmetric and
    intentionally conservative about turnover but not broker-equivalent.
    """
    if mode not in {"original", "inverse", "random"}:
        raise ValueError("invalid inversion mode")
    rng=Random(seed)
    cursor=0
    baseline=0
    held=0
    equity=gross=1.0
    peak=1.0
    maximum_drawdown=0.0
    changes=legs=active=0
    prior_close=None
    points=[]
    for b in bars:
        at=_utc(b.bar_time)
        if at<start:
            prior_close=float(b.close)
            while cursor<len(events) and events[cursor][0]<=at:
                cursor+=1
            continue
        if at>=end:
            break
        if prior_close is not None and held:
            gap_ret=1+held*notional*(float(b.open)/prior_close-1)
            gross*=max(0.0,gap_ret)
            equity*=max(0.0,gap_ret)
        desired=None
        while cursor<len(events) and events[cursor][0]<=at:
            desired=int(events[cursor][1])
            cursor+=1
        if desired is not None and desired!=baseline:
            # Charge every strategy for the same signed baseline decision's
            # absolute turnover, including two legs on direct reversal.
            traded=abs(desired-baseline)
            legs+=traded
            equity*=max(0.0,1-notional*traded*cost_bps/10000)
            baseline=desired
            new_position=(desired if mode=="original" else -desired
                          if mode=="inverse" else rng.choice((-1,1)))
            if new_position!=held:
                changes+=1
            held=new_position
        if held:
            active+=1
            bar_ret=1+held*notional*(float(b.close)/float(b.open)-1)
            gross*=max(0.0,bar_ret)
            equity*=max(0.0,bar_ret)
        peak=max(peak,equity)
        if peak>0:
            maximum_drawdown=max(maximum_drawdown,100*(1-equity/peak))
        points.append((at.isoformat(),(equity-1)*100))
        prior_close=float(b.close)
    return {"net":(equity-1)*100,"gross":(gross-1)*100,
            "cost":(gross-equity)*100,"max_dd":maximum_drawdown,
            "changes":changes,"turnover":legs,"active":active,
            "points":tuple(points)}


def run_inversion_experiment(bars: Sequence, *, started_at, ended_at,
                             minutes: Sequence[int]=(5,15),
                             notional_fraction=.2,commission_side_bps=8.,
                             spread_bps=1.,seed=20261015,
                             random_controls=DEFAULT_RANDOM_CONTROLS):
    """Same candle window and exact signal changes for original/inverted/control."""
    if (not isfinite(notional_fraction) or not 0<notional_fraction<=1
        or not all(isfinite(x) and x>=0 for x in
                   (commission_side_bps,spread_bps))
        or not 1<=random_controls<=200):
        raise ValueError("invalid experiment assumptions")
    prepared,start,end=_research_bars(bars,started_at=started_at,ended_at=ended_at)
    if start>=end:
        raise ValueError("start must precede end")
    selected=tuple(dict.fromkeys(minutes))
    if not selected or any(n not in PERMITTED_MINUTES for n in selected):
        raise ValueError("unsupported signal timeframe")
    cost=commission_side_bps+spread_bps/2
    result=[]
    placebo=[]
    scored_bars=sum(start<=_utc(b.bar_time)<end for b in prepared)
    for tf in selected:
        for model in ("MACD Flip","Histogram Peak Flip"):
            events=_signal_target_events(prepared,tf,model)
            test_id=f"{model}:{tf}"
            samples=[]
            for variant in ("Original","Invertert"):
                mode="original" if variant=="Original" else "inverse"
                scored=_score(prepared,events,start=start,end=end,
                              notional=notional_fraction,cost_bps=cost,
                              mode=mode,seed=seed)
                result.append(InversionResult(model,tf,variant,
                              round(scored["net"],5),round(scored["gross"],5),
                              round(scored["cost"],5),round(scored["max_dd"],5),
                              scored["changes"],scored["turnover"],
                              scored["active"],scored["points"]))
            for n in range(random_controls):
                samples.append(_score(prepared,events,start=start,end=end,
                               notional=notional_fraction,cost_bps=cost,
                               mode="random",seed=seed+n+101)["net"])
            ordered=sorted(samples)
            placebo.append((model,tf,round(median(samples),5),
                            round(ordered[int((len(samples)-1)*.10)],5),
                            round(ordered[int((len(samples)-1)*.90)],5)))
    return InversionExperiment(INVERSION_VERSION,start.isoformat(),
             end.isoformat(),scored_bars,notional_fraction,cost,
             tuple(result),tuple(placebo))


__all__=["run_inversion_experiment","InversionResult","InversionExperiment",
         "INVERSION_VERSION","PERMITTED_MINUTES","_signal_target_events"]
