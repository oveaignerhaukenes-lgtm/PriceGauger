"""Bounded one-hour signal calibration for IC14; no broker calls or writes.
Estimates characteristic impulse and pullback scales, not optimal returns.
Only the five main controls are proposed; no emergency or account changes.
"""
from dataclasses import dataclass
from datetime import timedelta
from math import isfinite
from statistics import median
from autotrader_impulse_catcher_v14 import SLIDERS,normalize_settings

def quantile(values,q):
    a=sorted(values)
    if not a:raise ValueError("Insufficient observations")
    i=(len(a)-1)*q
    lo=int(i);hi=min(lo+1,len(a)-1)
    return a[lo]+(a[hi]-a[lo])*(i-lo)

def bound(name,v):
    lo,hi,step,default=SLIDERS[name]
    x=min(hi,max(lo,lo+round((v-lo)/step)*step))
    return int(x) if isinstance(default,int) else round(x,6)

@dataclass(frozen=True)
class AutoProposal:
    settings:dict
    evidence:dict

def propose_ic14(quotes,*,now,side,current):
    """Measure a fixed trailing hour. Reject stale/insufficient coverage.
    No hindsight-based trade selection; directional excursions are descriptive.
    """
    if now.tzinfo is None or side not in ("LONG","SHORT"):
        raise ValueError("Invalid calibration context")
    current=normalize_settings(current)
    start=now-timedelta(hours=1)
    q=[x for x in quotes if start<=x.at<=now]
    if len(q)<1800 or (now-q[-1].at).total_seconds()>15 or (q[0].at-start).total_seconds()>120:
        raise ValueError("For lite fersk sekunddata i siste time")
    if any(not isfinite(x.mid) or not 0<x.bid<=x.ask for x in q):
        raise ValueError("Ugyldige BBO-data")
    gaps=[(b.at-a.at).total_seconds() for a,b in zip(q,q[1:])]
    if any(dt<=0 for dt in gaps) or sum(dt for dt in gaps if dt>4)>360:
        raise ValueError("For store datagap i siste time")
    sign=1 if side=="LONG" else -1
    w=current["fast_window"]
    moves=[];directional=[];runs=[];retraces=[];recovery=[]
    j=0
    # Nonoverlapping genuine windows; no return across missing observations.
    for i in range(1,len(q)):
        dt=(q[i].at-q[j].at).total_seconds()
        if gaps[i-1]>2:
            j=i;continue
        if dt>=w:
            d=sign*(q[i].mid-q[j].mid)
            moves.append(abs(d))
            if d>0:directional.append(d)
            j=i
    if len(directional)<30 or len(moves)<100:
        raise ValueError("For få observerte impulsvinduer")
    noise=median(moves)
    impulse=quantile(directional,.85)
    spread=median(x.ask-x.bid for x in q)
    # Detect same-direction runs and recoverable pullbacks via a fixed,
    # observed zigzag threshold. Never count unfinished runs as completed.
    turn=max(2*spread,noise,1.)
    trend=0;anchor=peak=q[0].mid;started=q[0].at
    pull_started=None;pull_low=None
    for i,x in enumerate(q[1:],1):
        p=x.mid
        if gaps[i-1]>2:
            trend=0;anchor=peak=p;started=x.at;pull_started=pull_low=None
            continue
        if trend==0:
            if sign*(p-anchor)>=turn:
                trend=1;peak=p;started=x.at
            elif sign*(p-anchor)<=-turn:
                anchor=peak=p;started=x.at
            continue
        depth=sign*(peak-p)
        if depth<0:
            if pull_started is not None and pull_low is not None:
                run=sign*(peak-anchor)
                if run>0:
                    retraces.append(max(0.,sign*(peak-pull_low))/run)
                    recovery.append((x.at-pull_started).total_seconds())
            peak=p;pull_started=pull_low=None
        elif depth>=turn:
            runs.append((x.at-started).total_seconds())
            trend=0;anchor=peak=p;started=x.at;pull_started=pull_low=None
        elif depth>0:
            if pull_started is None:pull_started=x.at;pull_low=p
            elif sign*(p-pull_low)<0:pull_low=p
    # Attack is bounded by the measured fast arm; hold/release derive from
    # typical observed runs and recovered dips, not realized profit.
    changes={"min_impulse_points":bound("min_impulse_points",max(impulse,2*spread)),
             "entry_confirmation_seconds":bound("entry_confirmation_seconds",w*.4),
             "minimum_hold_seconds":bound("minimum_hold_seconds",quantile(runs,.5) if len(runs)>=15 else current["minimum_hold_seconds"]),
             "retrace_fraction":bound("retrace_fraction",quantile(retraces,.75) if len(retraces)>=15 else current["retrace_fraction"]),
             "exit_confirmation_seconds":bound("exit_confirmation_seconds",quantile(recovery,.75) if len(recovery)>=15 else current["exit_confirmation_seconds"])}
    return AutoProposal(normalize_settings({**current,**changes}),{
        "quotes":len(q),"start":q[0].at.isoformat(),"end":q[-1].at.isoformat(),
        "spread":spread,"median_move":noise,"directional_p85":impulse,
        "runs":len(runs),"recovered_pullbacks":len(recovery),"window_s":w,
        "gap_seconds":sum(dt for dt in gaps if dt>4)})
