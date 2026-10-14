"""Descriptive AEn turnover/whipsaw diagnostics. No trade authority.

Focus on explaining WHY gross directional accuracy can lose money after
repeated micro-reversals, not optimizing parameters on the same holdout.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from aen_replay_v1 import utc


@dataclass(frozen=True)
class ChurnMetrics:
    fills: int
    total_units: int
    round_trips: int
    exit_to_reentry_under_1m: int
    exit_to_reentry_under_2m: int
    exit_to_reentry_under_5m: int
    opposite_reentry_under_5m: int
    estimated_cost_drag_pct: float


def turnover_diagnostics(report):
    """Measure FLAT→reentry churn; deltas use modeled fill timestamps.

    An exit followed by same-direction or opposite-direction entry qualifies
    only if a genuinely flat inventory was recorded between these two fills.
    Aggregation is descriptive, NOT an assertion of profitability.
    """
    fills=tuple(sorted(report.fills,key=lambda x:utc(x[0])))
    exits=[]
    churn=[]
    round_trips=0
    previous=0
    for stamp,units,*_ in fills:
        side=1 if units>0 else -1 if units<0 else 0
        old=1 if previous>0 else -1 if previous<0 else 0
        if old and side==0:
            exits.append((utc(stamp),old))
            round_trips+=1
        elif old==0 and side and exits:
            when,old_side=exits.pop()
            elapsed=utc(stamp)-when
            if timedelta(0)<=elapsed<=timedelta(minutes=5):
                churn.append((elapsed.total_seconds()/60,side!=old_side))
        previous=int(units)
    return ChurnMetrics(
        fills=len(fills),total_units=int(report.turnover_units),
        round_trips=round_trips,
        exit_to_reentry_under_1m=sum(t<=1 for t,_ in churn),
        exit_to_reentry_under_2m=sum(t<=2 for t,_ in churn),
        exit_to_reentry_under_5m=len(churn),
        opposite_reentry_under_5m=sum(opposite for _,opposite in churn),
        estimated_cost_drag_pct=round(report.gross_pct-report.return_pct,5),
    )
