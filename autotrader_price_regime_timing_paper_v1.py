"""PAPER-only early structural turn: 30/60m price trend over a 6h backdrop.

All inputs are completed, contiguous 1m OHLC from one already-verified Saxo
instrument. Arithmetic mean of 1m typical prices is a time-equal PRICE proxy,
not volume-weighted VWAP nor an actual intraminute TWAP. No LIVE routing,
broker requests, persisted decisions or orders.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median

from autotrader_price_structure_regime_paper_v1 import _classify_completed_window
from autotrader_v3_macd_stoch_v21_split_v1 import _completed_bars, _utc


@dataclass(frozen=True, slots=True)
class PriceRegimeTimingPaper:
    primary: str = "UKJENT"
    local: str = "UKJENT"
    effective_for_impulse_exit: str = "UKJENT"
    regime_long_allowed: bool = True
    regime_short_allowed: bool = True
    mean_price_30: float | None = None
    mean_price_60: float | None = None


@dataclass(frozen=True, slots=True)
class PriceRegimeTimingTimelinePaper:
    closed_at: tuple[datetime, ...]
    observations: tuple[PriceRegimeTimingPaper, ...]

    def state_asof(self, at: datetime) -> PriceRegimeTimingPaper:
        stamp=_utc(at)
        index=bisect_right(self.closed_at, stamp)-1
        if index<0 or stamp-self.closed_at[index]>=timedelta(minutes=1):
            return PriceRegimeTimingPaper()
        return self.observations[index]


def _typical_price(bar) -> float:
    return (float(bar.high)+float(bar.low)+float(bar.close))/3.


def _local_direction(bars, *, minutes: int) -> str:
    """Signed, normalized price trend; 30m requires a stronger breakout."""
    if len(bars)!=minutes+1:
        return "UKJENT"
    closes=[float(b.close) for b in bars]
    typical=[_typical_price(b) for b in bars]
    ranges=[max(float(b.high)-float(b.low),
                abs(float(b.high)-float(a.close)),
                abs(float(b.low)-float(a.close)))
            for a,b in zip(bars,bars[1:])]
    noise=median(ranges)
    path=sum(abs(b-a) for a,b in zip(closes,closes[1:]))
    if noise<=0 or path<=0:
        return "UKJENT"
    displacement=closes[-1]-closes[0]
    same_direction_fraction=(sum((b-a)*displacement>0
                                 for a,b in zip(closes,closes[1:]))/minutes)
    average=sum(typical[1:]) / minutes
    recent=typical[-10:] if minutes==30 else typical[-15:]
    previous=typical[-20:-10] if minutes==30 else typical[-30:-15]
    prior_high=max(float(b.high) for b in bars[-31:-11]) if minutes==30 else 0.
    prior_low=min(float(b.low) for b in bars[-31:-11]) if minutes==30 else 0.
    last_lows=min(float(b.low) for b in bars[-10:])
    preceding_lows=min(float(b.low) for b in bars[-20:-10])
    last_highs=max(float(b.high) for b in bars[-10:])
    preceding_highs=max(float(b.high) for b in bars[-20:-10])
    if minutes==60:
        first_half,last_half=bars[:30],bars[-30:]
        upwards_structure=(
            max(b.high for b in last_half)>max(b.high for b in first_half)
            and min(b.low for b in last_half)>min(b.low for b in first_half))
        downwards_structure=(
            max(b.high for b in last_half)<max(b.high for b in first_half)
            and min(b.low for b in last_half)<min(b.low for b in first_half))
    else:
        upwards_structure=(closes[-1]>prior_high and last_lows>preceding_lows)
        downwards_structure=(closes[-1]<prior_low and last_highs<preceding_highs)

    enough_movement=abs(displacement)>=(3. if minutes==30 else 5.)*noise
    efficiency=abs(displacement)/path
    enough_efficiency=efficiency>=(.50 if minutes==30 else .35)
    enough_consistency=same_direction_fraction>=(.67 if minutes==30 else .75)
    if not (enough_movement and enough_efficiency and enough_consistency):
        return "UKJENT"
    if (displacement>0 and closes[-1]>average+.5*noise and
            sum(recent)>sum(previous) and upwards_structure):
        return "BULL"
    if (displacement<0 and closes[-1]<average-.5*noise and
            sum(recent)<sum(previous) and downwards_structure):
        return "BEAR"
    return "UKJENT"


def _timed_observation(rows, consecutive: int) -> PriceRegimeTimingPaper:
    primary=(
        _classify_completed_window(rows[-361:]).state
        if consecutive>=361 else "UKJENT"
    )
    mean30=(sum(_typical_price(b) for b in rows[-30:])/30
            if consecutive>=30 else None)
    mean60=(sum(_typical_price(b) for b in rows[-60:])/60
            if consecutive>=60 else None)
    local="UKJENT"
    if consecutive>=61:
        direction=_local_direction(rows[-61:],minutes=60)
        if direction!="UKJENT":
            local=direction+"_60"
    if local=="UKJENT" and consecutive>=31:
        direction=_local_direction(rows[-31:],minutes=30)
        if direction!="UKJENT":
            local=direction+"_30"

    long_allowed=not (primary=="BEAR" and not local.startswith("BULL_"))
    short_allowed=not (primary=="BULL" and not local.startswith("BEAR_"))
    if local.endswith("_60"):
        effective=local[:4]
    elif (primary=="BEAR" and local=="BULL_30") or (
        primary=="BULL" and local=="BEAR_30"):
        # Initial strong reversal is a transition, not confirmed main trend.
        effective="UKJENT"
    else:
        effective=primary
    return PriceRegimeTimingPaper(primary,local,effective,
                                  long_allowed,short_allowed,mean30,mean60)


def price_regime_timing_timeline_paper(*, source_bars, cutoff,
                                       market_name: str) -> PriceRegimeTimingTimelinePaper:
    """Causal one-pass history: no warmup forced to six hours for local turns."""
    rows=_completed_bars(source_bars,timeframe=1,cutoff=cutoff,market=market_name)
    stamps,observations=[],[]
    consecutive=0
    previous=None
    for index,bar in enumerate(rows):
        stamp=_utc(bar.bar_time)
        consecutive=(consecutive+1 if previous is not None and
                     stamp-previous==timedelta(minutes=1) else 1)
        previous=stamp
        stamps.append(stamp+timedelta(minutes=1))
        observations.append(_timed_observation(rows[max(0,index-360):index+1],consecutive))
    return PriceRegimeTimingTimelinePaper(tuple(stamps),tuple(observations))
