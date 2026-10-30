"""Strict, causal 1s Saxo BBO PAPER replay for directional impulse collectors.

No broker, database or state mutations. Real stored bid/ask quotes only, no
interpolation. Decisions from the last observed mid; fills at NEXT recorded
quote using the actual historical observed half-spread cost plus scenarios.
"""
from __future__ import annotations

from collections import deque
from datetime import timedelta
from math import isfinite
from dataclasses import replace
from typing import Sequence

from algorithm_lab_v1 import (
    LabCosts, LabPoint, LabResult, LabTrade, utc, validate_plan,
)

MAX_QUOTES = 18000
MAX_GAP_SECONDS = 4.0


def replay_tick_impulses(*, plan: dict, quotes: Sequence, costs: LabCosts,
                         start_at, end_at) -> LabResult:
    p = validate_plan(plan)
    if p["kind"] != "impulse":
        raise ValueError("Sekundbasert replay støtter foreløpig bare impulsstrategier.")
    if p["regime_rule"] != "none":
        raise ValueError("Regimefiltrert 1s-replay er ikke implementert: avvis, ikke ignorer filteret.")
    start, end = utc(start_at), utc(end_at)
    if end <= start:
        raise ValueError("Slutt må være etter start.")
    if len(quotes) > MAX_QUOTES:
        raise ValueError(f"Maks {MAX_QUOTES} ekte 1s-observasjoner per kjøring.")
    rows = []
    previous_time = None
    for row in quotes:
        # Never silently accept malformed or duplicated provider quotes.
        t = utc(row["quote_at"])
        bid, ask = float(row["bid"]), float(row["ask"])
        if (previous_time is not None and t <= previous_time
                or not isfinite(bid) or not isfinite(ask)
                or bid <= 0 or ask < bid):
            raise ValueError("Ugyldige, usorterte eller dupliserte lagrede Saxo BBO.")
        previous_time = t
        rows.append((t, bid, ask, (bid + ask) / 2))
    if not rows:
        raise ValueError("Ingen lagrede 1s BBO-priser i valgt vindu.")

    side = 1 if p["side"] == "long" else -1
    position = 0.
    nav = peak = costs.starting_nav_nok
    spent = max_dd = 0.
    gaps = 0
    pending = None
    entered_at = None
    previous = None
    history = deque()
    trades = []
    points = []

    def charge(bid, ask, lots):
        mid = (bid + ask) / 2
        # Exact observed BBO half spread for EACH execution, not input spread_bps.
        return abs(lots) * (
            (ask - bid) / 2 * costs.point_value_nok
            + mid * costs.point_value_nok * (
                costs.slippage_bps / 10000 + costs.variable_fee_bps / 10000
            )) + costs.commission_nok

    for t, bid, ask, mid in rows:
        if t >= end:
            break
        if previous is not None and (t-previous[0]).total_seconds() > MAX_GAP_SECONDS:
            gaps += 1
            if position:
                old_t, old_bid, old_ask, old_mid = previous
                fee = charge(old_bid, old_ask, position)
                nav -= fee
                spent += fee
                trades.append(LabTrade(old_t, "GAP_FLAT", old_mid,
                                       position, 0., fee,
                                       "Uobserved quote gap; paper liquidation at last valid BBO"))
            position = 0.
            pending = None
            entered_at = None
            history.clear()
            previous = None

        if t >= start:
            if previous is not None and position:
                nav += position * (mid - previous[3]) * costs.point_value_nok
            if pending is not None:
                target, reason = pending
                if target != position:
                    fee = charge(bid, ask, target-position)
                    nav -= fee
                    spent += fee
                    trades.append(LabTrade(t, "OPEN" if target else "FLAT",
                                           mid, position, target, fee, reason))
                    position = target
                    entered_at = t if target else None
                pending = None
        elif position:
            raise AssertionError("PAPER-position kan ikke opprettes før start.")

        history.append((t, mid))
        target_time = t-timedelta(seconds=p["lookback"])
        while len(history) > 1 and history[1][0] <= target_time:
            history.popleft()
        anchor = history[0] if history and history[0][0] <= target_time else None
        # A time gap can invalidate the lookback even when quote positions exist.
        if anchor is not None and (target_time-anchor[0]).total_seconds() > 2:
            anchor = None
        signal = "WARMUP"
        if start <= t < end:
            if anchor is not None:
                momentum = side * (mid / anchor[1] - 1) * 10000
                if position:
                    held = (t-entered_at).total_seconds() if entered_at else 0
                    if (momentum < p["fade_bps"]
                            or momentum <= -p["exit_bps"]
                            or held >= p["max_hold"]):
                        pending = (0., "Impulse decay, adverse movement or max hold")
                        signal = "EXIT"
                    else:
                        signal = "HOLD"
                elif momentum >= p["entry_bps"]:
                    pending = (side * costs.lot_size,
                               "Observed quote impulse; next observed quote entry")
                    signal = "ENTRY"
                else:
                    signal = "FLAT"
            if nav <= 0:
                raise ValueError("PAPER-kapitalen er oppbrukt med valgte parametere.")
            peak = max(peak, nav)
            max_dd = max(max_dd, 100 * (peak-nav) / peak)
            points.append(LabPoint(t, mid, nav, position, signal, "TICK"))
        previous = (t, bid, ask, mid)

    if not points:
        raise ValueError("Ingen godkjente 1s-observasjoner i valgt testperiode.")
    if position:
        # Last known bid/ask, not fabricated future quote.
        last_t, bid, ask, mid = previous
        fee = charge(bid, ask, position)
        nav -= fee
        spent += fee
        trades.append(LabTrade(last_t, "END_FLAT", mid, position, 0., fee,
                               "Research liquidation at last recorded BBO; not real Saxo fill"))
        points[-1] = replace(points[-1], nav_nok=nav, position=0., signal="END_FLAT")
        max_dd = max(max_dd, 100 * (peak-nav) / peak)
    return LabResult(tuple(points), tuple(trades), nav-costs.starting_nav_nok,
                     100 * (nav/costs.starting_nav_nok-1), max_dd, spent,
                     gaps, 0, len(rows))


__all__ = ["MAX_QUOTES", "replay_tick_impulses"]
