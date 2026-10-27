"""Observed Saxo 1-second BBO momentum-threshold event study.

No broker orders, no predicted prices, no simulated fill assumption beyond
marked bid/ask horizon prices. Events are selected from PAST quotes only and
are nonoverlapping within each threshold's test series. Future quotes are used
ONLY to measure outcomes. Rates are conditional descriptive frequencies, not
a verified live trading edge or NOK P/L.
"""
from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from statistics import median
from typing import Sequence

LOOKBACKS_SECONDS = (5, 10, 20, 30)
THRESHOLDS_BPS = (2., 4., 6., 8., 10., 15., 20.)
HORIZONS_SECONDS = (30, 60, 120)
MAX_ROWS = 80000
MAX_GAP_SECONDS = 4
MAX_QUOTE_DELAY_SECONDS = 5
COOLDOWN_SECONDS = 125


@dataclass(frozen=True)
class BboSecond:
    at: datetime
    received: datetime
    bid: float
    ask: float

    @property
    def mid(self) -> float:
        return (self.bid + self.ask)*0.5

    @property
    def spread_bps(self) -> float:
        return 10000*(self.ask-self.bid)/self.mid


@dataclass(frozen=True)
class ImpulseOutcome:
    triggered_at: datetime
    direction: str
    lookback_seconds: int
    threshold_bps: float
    triggered_move_bps: float
    horizon_seconds: int
    observed_net_bps: float
    observed_mid_bps: float
    max_continuation_bps: float
    max_adverse_bps: float
    peak_seconds: float
    retraced_from_peak_pct: float | None
    crossed_half_threshold_first: bool | None
    bidask_spread_bps: float


@dataclass(frozen=True)
class ImpulseAggregate:
    sample: str
    lookback_seconds: int
    threshold_bps: float
    horizon_seconds: int
    events: int
    median_net_bps: float | None
    profitable_fraction: float | None
    continued_half_threshold_fraction: float | None
    median_max_continuation_bps: float | None
    median_time_to_peak_seconds: float | None
    median_retraced_from_peak_pct: float | None
    median_spread_bps: float | None


def _utc(value) -> datetime:
    t=(value if isinstance(value,datetime)
       else datetime.fromisoformat(str(value).replace("Z","+00:00")))
    if t.tzinfo is None:
        raise ValueError("quote timestamps must include timezone")
    return t.astimezone(timezone.utc)


def prepare_second_quotes(rows: Sequence) -> tuple[tuple[BboSecond, ...],...]:
    """Fail closed on invalid quotes and split any unobserved/stale intervals."""
    if len(rows)>MAX_ROWS: raise ValueError("too many quotes; restrict time range")
    sessions=[]
    current=[]
    last=None
    for row in rows:
        try:
            q=BboSecond(
                _utc(row["quote_at"]),_utc(row["received_at"]),
                float(row["bid"]),float(row["ask"]))
        except (KeyError,TypeError,ValueError,OverflowError) as exc:
            raise ValueError("invalid quote timestamp or price") from exc
        if (not all(isfinite(x) and x>0 for x in (q.bid,q.ask))
                or q.ask<q.bid or (last and q.at<=last.at)):
            raise ValueError("duplicate, unordered or crossed quotes")
        lag=(q.received-q.at).total_seconds()
        if lag< -2 or lag>MAX_QUOTE_DELAY_SECONDS:
            if len(current)>=180: sessions.append(tuple(current))
            current=[]
            last=q
            continue
        if last and ((q.at-last.at).total_seconds()>MAX_GAP_SECONDS
                     or (q.at-last.at).total_seconds()<=0):
            if len(current)>=180: sessions.append(tuple(current))
            current=[]
        current.append(q)
        last=q
    if len(current)>=180: sessions.append(tuple(current))
    return tuple(sessions)


def _outcome(session: Sequence[BboSecond], times: Sequence[datetime],
             index: int, *, side:int, lookback:int, threshold:float,
             horizon:int, move:float) -> ImpulseOutcome | None:
    trigger=session[index]
    end_at=trigger.at+timedelta(seconds=horizon)
    last=bisect_left(times,end_at)
    if last>=len(session) or (session[last].at-end_at).total_seconds()>2:
        return None
    path=session[index+1:last+1]
    if not path: return None
    entry=trigger.ask if side>0 else trigger.bid
    end=path[-1]
    exit_price=end.bid if side>0 else end.ask
    net=10000*side*(exit_price-entry)/trigger.mid
    mid=10000*side*(end.mid-trigger.mid)/trigger.mid
    signed=[10000*side*(q.mid-trigger.mid)/trigger.mid for q in path]
    best=max(0.,*signed)
    worst=min(0.,*signed)
    peak_idx=signed.index(max(signed))
    peak_at=path[peak_idx].at
    retraced=(max(0.,best-mid)/best*100.) if best>1e-9 else None
    half=threshold/2.
    crossed=None
    for value in signed:
        if value>=half:
            crossed=True
            break
        if value<=-half:
            crossed=False
            break
    return ImpulseOutcome(
        trigger.at,"LONG" if side>0 else "SHORT",lookback,threshold,move,
        horizon,net,mid,best,worst,
        (peak_at-trigger.at).total_seconds(),retraced,crossed,
        trigger.spread_bps,
    )


def study_thresholds(
    sessions: Sequence[Sequence[BboSecond]], *,
    lookbacks: Sequence[int]=LOOKBACKS_SECONDS,
    thresholds: Sequence[float]=THRESHOLDS_BPS,
    horizons: Sequence[int]=HORIZONS_SECONDS,
    chronological_cutoff: datetime | None=None,
) -> tuple[ImpulseOutcome,...]:
    """First causal threshold crossing, avoid overlapping 120-second outcomes.

    Each selected 5/10/20/30s window is strictly in the past. If a threshold
    is met, its future 30/60/120s returns are scored separately; selection
    moves on only after complete 120s embargo, preventing one impulse from
    inflating evidence through dozens of overlapping event starts.
    """
    boundary=_utc(chronological_cutoff) if chronological_cutoff else None
    if any(x not in LOOKBACKS_SECONDS for x in lookbacks):
        raise ValueError("unsupported lookback")
    if any(x not in THRESHOLDS_BPS for x in thresholds):
        raise ValueError("unsupported threshold")
    if any(x not in HORIZONS_SECONDS for x in horizons):
        raise ValueError("unsupported horizon")
    out=[]
    for session in sessions:
        if len(session)<180: continue
        times=[q.at for q in session]
        prices=[q.mid for q in session]
        for lookback in lookbacks:
            for threshold in thresholds:
                last_event_at=None
                armed=True
                for i in range(len(session)):
                    if i<lookback: continue
                    q=session[i]
                    if last_event_at and (
                        q.at-last_event_at).total_seconds()<COOLDOWN_SECONDS:
                        continue
                    anchor_at=q.at-timedelta(seconds=lookback)
                    a=bisect_left(times,anchor_at)
                    if a>=i or (times[a]-anchor_at).total_seconds()>2:
                        continue
                    ret=10000*(prices[i]/prices[a]-1.)
                    if abs(ret)<=threshold*.5:
                        armed=True
                    if not armed or abs(ret)<threshold:
                        continue
                    # Trigger is known at quote RECEIPT, not before. Entry is
                    # reported only as indicative, no same-tick fill guarantee.
                    if (q.received-q.at).total_seconds()>MAX_QUOTE_DELAY_SECONDS:
                        continue
                    eligible=(q.at+timedelta(seconds=max(horizons))<=times[-1])
                    if not eligible: continue
                    side=1 if ret>0 else -1
                    outcomes=[]
                    for horizon in horizons:
                        result=_outcome(session,times,i,side=side,
                                        lookback=lookback,threshold=threshold,
                                        horizon=horizon,move=ret)
                        if result is not None:
                            outcomes.append(result)
                    if len(outcomes)!=len(horizons):
                        continue
                    out.extend(outcomes)
                    last_event_at=q.at
                    armed=False
    return tuple(out)


def summarize_thresholds(
    outcomes: Sequence[ImpulseOutcome], *, chronological_cutoff: datetime
) -> tuple[ImpulseAggregate,...]:
    boundary=_utc(chronological_cutoff)
    by={}
    for ev in outcomes:
        sample="FØRSTE_70PCT" if ev.triggered_at<boundary else "SISTE_30PCT"
        by.setdefault((sample,ev.lookback_seconds,ev.threshold_bps,
                       ev.horizon_seconds),[]).append(ev)
    results=[]
    for (sample,lb,thr,horizon),events in sorted(by.items()):
        def pct(values):return sum(values)/len(values) if values else None
        seen=[ev.crossed_half_threshold_first for ev in events
              if ev.crossed_half_threshold_first is not None]
        recoveries=[ev.retraced_from_peak_pct for ev in events
                    if ev.retraced_from_peak_pct is not None]
        results.append(ImpulseAggregate(
            sample,lb,thr,horizon,len(events),
            median(ev.observed_net_bps for ev in events),
            pct([ev.observed_net_bps>0 for ev in events]),
            pct(seen),
            median(ev.max_continuation_bps for ev in events),
            median(ev.peak_seconds for ev in events),
            median(recoveries) if recoveries else None,
            median(ev.bidask_spread_bps for ev in events),
        ))
    return tuple(results)


def chronological_split_at(sessions:Sequence[Sequence[BboSecond]]) -> datetime:
    points=[q.at for segment in sessions for q in segment]
    if len(points)<500:
        raise ValueError("insufficient contiguous 1s BBO history")
    return points[int(len(points)*.7)]
