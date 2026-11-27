"""Read-only, fixed-signal PAPER execution scenario; not a live broker replay.

Match the very same preview signals to observed BBO after an assumed delay.
Never interpolate, force-close or count a skipped/unfinished trade as profit.
The signal path itself is unchanged by hypothetical fill outcomes.
"""
from bisect import bisect_left,bisect_right
from dataclasses import dataclass
from datetime import timedelta
from math import isfinite
from statistics import median

@dataclass(frozen=True)
class CostTrade:
    entry_signal:object
    exit_signal:object
    entry_fill:object
    exit_fill:object
    signal_gross:float
    execution_gross:float
    spread:float
    delay_drag:float
    net:float

@dataclass(frozen=True)
class CostReport:
    signals:int
    completed_signals:int
    trades:tuple
    skipped:int
    incomplete:int
    carry_in:bool
    quote_count:int
    coverage:float
    median_spread:float|None

    @property
    def gross(self):return sum(t.signal_gross for t in self.trades)
    @property
    def spread(self):return sum(t.spread for t in self.trades)
    @property
    def delay_drag(self):return sum(t.delay_drag for t in self.trades)
    @property
    def net(self):return sum(t.net for t in self.trades)
    @property
    def wins(self):return sum(t.net>0 for t in self.trades)

def estimate_costs(quotes,trace,*,side,start,end,delay_s=3.,extra_points=0.,max_gap_s=4.):
    if side not in ("LONG","SHORT") or start>=end or not all(isfinite(x) for x in (delay_s,extra_points,max_gap_s)) or not (0<=delay_s<=30 and extra_points>=0 and max_gap_s>0):
        raise ValueError("invalid scenario")
    qs=tuple(q for q in quotes if start<=q.at<=end)
    times=[q.at for q in qs]
    if any(a>=b for a,b in zip(times,times[1:])) or any(not (isfinite(q.bid) and isfinite(q.ask) and 0<q.bid<=q.ask) for q in qs):
        raise ValueError("invalid BBO")
    # One prefix sum lets us test any interval for a feed hole in O(1).
    gaps=[0]
    for a,b in zip(times,times[1:]):
        gaps.append(gaps[-1]+int((b-a).total_seconds()>max_gap_s))
    def fill(at):
        i=bisect_left(times,at)
        if i>=len(times) or times[i]!=at:return None
        j=bisect_left(times,at+timedelta(seconds=delay_s),lo=i)
        if j>=len(times) or gaps[j]!=gaps[i] or (times[j]-at).total_seconds()>delay_s+max_gap_s:
            return None
        return j
    sign=1 if side=="LONG" else -1
    signals=pairs=skipped=incomplete=0
    trades=[]
    entry=None
    last_exit_fill=None
    carry=False
    for r in trace:
        at=r["at"]
        if at<start:
            carry=r.get("target")==side
            continue
        if at>end:break
        decision=r.get("decision")
        if decision=="QUALIFIED_IMPULSE_V14":
            signals+=1
            if entry is not None:incomplete+=1
            entry=r
        elif decision and entry is not None:
            pairs+=1
            a,b=fill(entry["at"]),fill(at)
            if a is None or b is None or times[a]>=at or (last_exit_fill is not None and times[a]<=last_exit_fill) or gaps[b]!=gaps[a]:
                skipped+=1
            else:
                qa,qb=qs[a],qs[b]
                signal_gross=sign*(r["mid"]-entry["mid"])
                execution_gross=sign*(qb.mid-qa.mid)
                spread=((qa.ask-qa.bid)+(qb.ask-qb.bid))/2
                trades.append(CostTrade(entry["at"],at,qa.at,qb.at,signal_gross,execution_gross,spread,signal_gross-execution_gross,execution_gross-spread-extra_points))
                last_exit_fill=qb.at
            entry=None
    incomplete+=int(entry is not None)
    covered=sum(min(1.,(b-a).total_seconds()) for a,b in zip(times,times[1:]))
    coverage=min(1.,covered/(end-start).total_seconds())
    return CostReport(signals,pairs,tuple(trades),skipped,incomplete,carry,len(qs),coverage,median(q.ask-q.bid for q in qs) if qs else None)
