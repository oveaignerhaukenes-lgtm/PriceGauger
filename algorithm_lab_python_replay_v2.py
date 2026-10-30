"""Paper accounting adapter for Docker-generated causal Python directions.

Always mark directions (-1, 0, 1) as research decisions; next known open
only. This module has no broker API and does not execute model source.
"""
from __future__ import annotations

from datetime import timedelta
from dataclasses import replace
from math import isfinite
from typing import Sequence

from algorithm_lab_v1 import LabCosts, LabPoint, LabTrade, LabResult, utc


def replay_directions(*, bars: Sequence, directions: Sequence[int],
                      costs: LabCosts, start_at, end_at, fx_multiplier_at=None) -> LabResult:
    start, end = utc(start_at), utc(end_at)

    def point_value(at):
        factor=float(fx_multiplier_at(at)) if fx_multiplier_at is not None else 1.
        if not isfinite(factor) or not .001 <= factor <= 1000:
            raise ValueError("Missing or invalid historical FX rate.")
        return costs.point_value_nok*factor

    def fee(price, qty, at):
        return replace(costs,point_value_nok=point_value(at)).execution_cost(price,qty)
    if len(bars) != len(directions) or not bars:
        raise ValueError("One direction per exact historical 1m bar is required.")
    if any(type(x) is not int or x not in (-1,0,1) for x in directions):
        raise ValueError("Only signed directions -1/0/1 allowed.")
    if end <= start:
        raise ValueError("Invalid research window.")
    last_at = None
    position = 0.
    pending = None
    nav = peak = costs.starting_nav_nok
    total_cost = finance_total = max_dd = 0.
    trades, points = [], []
    prev_close = None
    for bar, direction in zip(bars, directions):
        stamp = utc(bar.bar_time)
        if last_at and stamp-last_at != timedelta(minutes=1):
            raise ValueError("The sandbox and replay require contiguous 1m bars.")
        op, close = float(bar.open), float(bar.close)
        if stamp >= end:
            break
        if stamp >= start:
            if prev_close is not None and position:
                nav += position*(op-prev_close)*point_value(stamp)
            if pending is not None:
                target = pending*costs.lot_size
                if target*position < 0:
                    target = 0.  # Explicit flat-first execution
                if target != position:
                    fee=fee(op,target-position,stamp)
                    nav-=fee
                    total_cost+=fee
                    trades.append(LabTrade(stamp,
                        "OPEN" if target else "FLAT",op,position,target,fee,
                        "Causal sandbox direction; next observed open"))
                    position=target
                pending=None
            if position:
                nav+=position*(close-op)*point_value(stamp+timedelta(minutes=1))
                annual=(costs.financing_long_annual_pct if position>0 else
                        costs.financing_short_annual_pct)
                finance=abs(position)*close*point_value(stamp+timedelta(minutes=1))*annual/100/(365*24*60)
                nav-=finance
                total_cost+=finance
                finance_total+=finance
            if nav<=0:
                raise ValueError("Sandbox scenario exhausted PAPER capital.")
            # The sandbox may request an opposite direction, but must first
            # flatten at next observed open, then decide again from a new bar.
            pending=direction
            peak=max(peak,nav)
            max_dd=max(max_dd,100*(peak-nav)/peak)
            points.append(LabPoint(stamp+timedelta(minutes=1),close,nav,position,
                                   ("LONG" if direction>0 else "SHORT" if direction<0 else "FLAT"),
                                   "PYTHON"))
        last_at=stamp
        prev_close=close
    if not points:
        raise ValueError("No measured replay bars.")
    if position:
        fee=fee(points[-1].close,position,points[-1].at)
        nav-=fee
        total_cost+=fee
        trades.append(LabTrade(points[-1].at,"END_FLAT",
                               points[-1].close,position,0.,fee,
                               "Counterfactual end liquidation"))
        points[-1]=replace(points[-1],nav_nok=nav,position=0.,signal="END_FLAT")
        max_dd=max(max_dd,100*(peak-nav)/peak)
    return LabResult(tuple(points),tuple(trades),nav-costs.starting_nav_nok,
                     100*(nav/costs.starting_nav_nok-1),max_dd,total_cost,
                     0,0,len(bars),finance_total)
