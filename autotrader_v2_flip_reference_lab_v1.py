"""Read-only V2 MACD Flip reference on canonical bars.

The V2 signal source is imported from the existing TradingDesk control, which
uses the same fully-closed timeframe MACD 12/26/9 cross logic as V2 LIVE.
This is NOT a V2 broker order replay: fill timing, broker latency, financing
and actual Saxo costs are estimates, and V2 bootstrap may differ.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Sequence

from autotrader_macd_timeframe_controls_v1 import _crosses_by_action_v1
from autotrader_macd_timeframe_live_v1 import LIVE_MACD_CONTROL_TIMEFRAMES_V1

REFERENCE_VERSION = "v2-macd-flip-closedbar-ref-v1"
SUPPORTED_V2_FLIP_MINUTES = tuple(LIVE_MACD_CONTROL_TIMEFRAMES_V1)


def _utc(value):
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z","+00:00"))
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class V2ReferenceReport:
    identity: str
    label: str
    points: tuple
    return_pct: float
    gross_pct: float
    max_drawdown_pct: float
    executions: int
    estimated_broker_orders: int
    total_cost_pct: float
    decisions: tuple
    completed_signal_bars: int


def reference_v2_flip(bars: Sequence, *, timeframe_minutes: int, started_at,
                      costs_enabled: bool=True, commission_side_bps: float=8.0,
                      quoted_spread_bps: float=1.0) -> V2ReferenceReport:
    """Compare V2 MACD cross targets with next-1m-open costed paper fills.

    V2's intent clock uses last two fully closed TF bars; this uses that same
    _crosses_by_action_v1 model to request a target. LIVE confirmation and
    broker-level CLOSE->FLAT->OPEN can take longer than this paper assumption.
    """
    tf=int(timeframe_minutes)
    if tf not in SUPPORTED_V2_FLIP_MINUTES:
        raise ValueError("timeframe not present in V2 MACD Flip LIVE adapter")
    if any(not isfinite(float(v)) or float(v)<0 for v in
           (commission_side_bps,quoted_spread_bps)):
        raise ValueError("negative or non-finite cost parameter")
    ident=f"{REFERENCE_VERSION}:tf{tf}"
    label=f"V2 ref · MACD {tf}m Flip"
    if not bars:
        return V2ReferenceReport(ident,label,(),0,0,0,0,0,0,(),0)
    ordered=sorted(bars,key=lambda b:_utc(b.bar_time))
    started=_utc(started_at)
    # Entire lookback is for indicator warmup only: pre-start trades and profits
    # are never included in the scored window.
    crosses=_crosses_by_action_v1(tuple(ordered),timeframe_minutes=tf)
    exposure=0.0
    pending=None
    gross=net=seed=10000.0
    paid=0.0
    count=orders=0
    previous_close=None
    points=[]
    decisions=[]
    side_cost=(commission_side_bps+quoted_spread_bps/2)/10000
    for bar in ordered:
        bar_start=_utc(bar.bar_time)
        action_time=bar_start+timedelta(minutes=1)
        opening=float(bar.open)
        closing=float(bar.close)
        if opening<=0 or closing<=0:
            raise ValueError("price must be positive")
        # Old confirmed position is exposed to overnight/weekend open gaps.
        if previous_close is not None and action_time>started:
            gap_return=opening/previous_close-1
            gross*=max(0,1+exposure*gap_return)
            net*=max(0,1+exposure*gap_return)
        # The TF-cross is known only after that bar CLOSED. Paper fill uses
        # NEXT canonical 1m open, not the cross candle's favorable close.
        if pending is not None and bar_start >= started:
            target,signal_at=pending
            if bar_start>=signal_at and target!=exposure:
                amount=abs(target-exposure)
                orders+=2 if target*exposure<0 else 1
                count+=1
                if costs_enabled:
                    cost=amount*side_cost*net
                    paid+=cost
                    net*=max(0,1-amount*side_cost)
                exposure=float(target)
                pending=None
        if action_time>started:
            bar_return=closing/opening-1
            gross*=max(0,1+exposure*bar_return)
            net*=max(0,1+exposure*bar_return)
            points.append((action_time.isoformat(),(net/seed-1)*100,
                           (gross/seed-1)*100))
        previous_close=closing
        direction=crosses.get(action_time)
        if direction is not None and action_time>=started:
            target=1.0 if direction=="LONG" else -1.0
            # At most one target per confirmed V2 MACD closed timeframe bar.
            if pending is None and target != exposure:
                decisions.append((action_time.isoformat(),direction,exposure,target))
                pending=(target,action_time)
    high=seed
    dd=0.0
    for _,pct,_ in points:
        equity=seed*(1+pct/100)
        high=max(high,equity)
        if high>0:
            dd=max(dd,100*(1-equity/high))
    return V2ReferenceReport(
        ident,label,tuple(points),(net/seed-1)*100,
        (gross/seed-1)*100,dd,count,orders,paid/seed*100,
        tuple(decisions),len([t for t in crosses if t>=started])
    )
