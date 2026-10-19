"""Causal read-model of the existing Fraktal#1 swing detector.

Its confirmed reversals (not hindsight pivot timestamps) regulate *how often*
a rhythm strategy may OPEN or BUILD. This does not predict swing direction,
change the 1m broker poll rate, or authorize an order.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Sequence

from autotrader_v3_fraktal1_v1 import (
    REVERSION_THRESHOLDS_PCT, CONTEXT_MAX_AGE_MINUTES,
    causal_closes_v1,
)
from autotrader_market_rhythm_v1 import confirmed_turns_v1

RECENT_MICRO_TURNS = 4
MAX_MICRO_GAP_MINUTES = 10
LAST_1M_REQUIRED = 13
FAST_MICRO_INTERVAL_MINUTES = 4
NORMAL_MICRO_INTERVAL_MINUTES = 9


@dataclass(frozen=True, slots=True)
class FractalCadenceV1:
    """Strictly historical read model computed for a single closed 1m bar."""
    level: str  # FAST, NORMAL, SLOW, UNKNOWN
    median_micro_confirm_minutes: float | None
    directions: tuple[int, int, int]
    last_confirmation: datetime | None
    reason: str


def _utc(value):
    parsed=value if isinstance(value, datetime) else datetime.fromisoformat(
        str(value).replace("Z","+00:00"))
    if parsed.tzinfo is None:
        parsed=parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _dir(turn):
    return 1 if turn.kind == "TROUGH" else -1


def fractal_cadence_v1(source_bars: Sequence, *, closed_at) -> FractalCadenceV1:
    """Derive cadence exclusively from already confirmed turns across three scales.

    A turn has a historical pivot_at but isn't known until confirmed_at. The
    current bar may be used at its close + 10s, matching Fraktal#1's own rule.
    A missing recent 1m candle, source gap or stale scale returns UNKNOWN.
    """
    cutoff=_utc(closed_at)
    unknown=lambda why: FractalCadenceV1("UNKNOWN",None,(0,0,0),None,why)
    if cutoff.second or cutoff.microsecond:
        return unknown("decision cutoff not on a closed 1m boundary")
    try:
        series=causal_closes_v1(source_bars,now=cutoff+timedelta(seconds=10))
    except (ValueError,TypeError,OverflowError,AttributeError):
        return unknown("invalid Fraktal#1 OHLC source")
    if len(series)<LAST_1M_REQUIRED or _utc(series.index[-1])!=cutoff:
        return unknown("incomplete latest 1m window")
    tail=series.index[-LAST_1M_REQUIRED:]
    if any(tail[j]-tail[j-1] != timedelta(minutes=1)
           for j in range(1,len(tail))):
        return unknown("missing 1m interval")
    turns=tuple(
        confirmed_turns_v1(series,reversal_pct=scale)
        for scale in REVERSION_THRESHOLDS_PCT
    )
    # Fraktal#1's thresholds are defined as micro/meso/macro in percent.
    last=tuple(group[-1] if group else None for group in turns)
    if any(item is None for item in last):
        return unknown("higher fractal scale has no confirmed reversal")
    if len(turns[0])<RECENT_MICRO_TURNS:
        return unknown("insufficient confirmed micro-turn sample")
    # Avoid using any reversal recognized before a gap as current context.
    last_segment=turns[0][-1].segment
    if any(item.segment!=last_segment for item in last):
        return unknown("fractal scales do not share a continuous session")
    for item,maximum in zip(last,CONTEXT_MAX_AGE_MINUTES):
        age=(cutoff-_utc(item.confirmed_at)).total_seconds()/60.0
        if age<0 or age>maximum:
            return unknown("stale or future fractal confirmation")
    recent=turns[0][-RECENT_MICRO_TURNS:]
    if any(item.segment != last_segment for item in recent):
        return unknown("micro-cycle crosses a missing-data segment")
    intervals=[
        (next_.confirmed_at-prev.confirmed_at).total_seconds()/60
        for prev,next_ in zip(recent,recent[1:])
    ]
    if not all(0<value<MAX_MICRO_GAP_MINUTES*10 for value in intervals):
        return unknown("invalid confirmed-turn durations")
    micro_interval=float(median(intervals))
    dirs=tuple(_dir(item) for item in last)
    same_three=len(set(dirs))==1
    same_first_two=dirs[0]==dirs[1]
    if same_three and micro_interval <= FAST_MICRO_INTERVAL_MINUTES:
        level="FAST"
    elif same_first_two and micro_interval <= NORMAL_MICRO_INTERVAL_MINUTES:
        level="NORMAL"
    else:
        level="SLOW"
    return FractalCadenceV1(
        level,micro_interval,dirs,_utc(last[0].confirmed_at),
        f"Fraktal#1 confirmed at/before {cutoff.isoformat()}: "
        f"median micro-turn interval {micro_interval:.1f}m; "
        f"scale directions={dirs}; build pace={level}"
    )


def cadence_interval_minutes_v1(level: str, *, strategy: str) -> int | None:
    """Restrictions relative to baseline: never faster than base strategy.

    RhythmBuild already handles closed 1m; RhythmTrend already builds only at
    closed 5m. A missing fractal sample NEVER authorizes increased exposure.
    """
    if strategy=="build":
        return {"FAST":1,"NORMAL":2,"SLOW":4,"UNKNOWN":None}[level]
    if strategy=="trend":
        return {"FAST":5,"NORMAL":10,"SLOW":15,"UNKNOWN":None}[level]
    raise ValueError(f"unknown cadence strategy: {strategy}")


__all__=["FractalCadenceV1","fractal_cadence_v1",
         "cadence_interval_minutes_v1"]
