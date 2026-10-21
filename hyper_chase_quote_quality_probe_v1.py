"""Bounded, read-only 1s Saxo BBO quality diagnostics for HyperChase.

No account IDs, quote prices, Saxo HTTP requests, orders, DDL or trading writes.
Runs once per minute independently of LIVE arming.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from math import isfinite

from database import connect
from live_sim_hyper_quotes_v1 import _utc
from live_sim_hyper_chase_10s_v1 import MAX_FEED_GAP_SECONDS, MAX_QUOTE_AGE_SECONDS, MAX_SPREAD_BPS


def summarize_hyper_quote_window(rows, *, now):
    clock = _utc(now)
    by_uic = defaultdict(list)
    for row in rows:
        try:
            uic = int(row["provider_uic"])
            quote_at = _utc(row["quote_at"])
            received_at = _utc(row["received_at"])
            bid, ask = float(row["bid"]), float(row["ask"])
            lag = (received_at - quote_at).total_seconds()
            if not (0 < bid <= ask and isfinite(bid) and isfinite(ask)):
                continue
            if not (-2 <= lag <= MAX_QUOTE_AGE_SECONDS):
                continue
            if not -2 <= (clock - quote_at).total_seconds() <= 120:
                continue
        except (KeyError, ValueError, TypeError, OverflowError):
            continue
        spread_bps = 10000 * (ask - bid) / ((ask + bid) / 2)
        by_uic[uic].append((quote_at, spread_bps))
    out = []
    for uic, points in sorted(by_uic.items()):
        samples = sorted(set(points), key=lambda p: p[0])
        recent = [(t, spr) for t, spr in samples if (clock - t).total_seconds() <= 60]
        if not recent:
            continue
        gaps = [(b[0] - a[0]).total_seconds() for a, b in zip(recent, recent[1:])]
        eligible = 0
        for j, (stamp, spread) in enumerate(recent):
            if spread > MAX_SPREAD_BPS:
                continue
            window = [(t, sp) for t, sp in samples if 0 <= (stamp - t).total_seconds() <= 10]
            if len(window) < 9:
                continue
            if not any(9 <= (stamp - t).total_seconds() <= 10 for t, _ in window):
                continue
            if any((b[0] - a[0]).total_seconds() > MAX_FEED_GAP_SECONDS for a, b in zip(window, window[1:])):
                continue
            eligible += 1
        out.append({
            "uic": uic,
            "quotes_60s": len(recent),
            "latest_age_s": round((clock - recent[-1][0]).total_seconds(), 2),
            "max_gap_s": round(max(gaps), 2) if gaps else None,
            "wide_spread_quotes": sum(sp > MAX_SPREAD_BPS for _, sp in recent),
            "valid_10s_windows": eligible,
        })
    return out


def probe_hyper_quote_quality_v1(*, db_path="pricegauger.db", now=None):
    """One bounded indexed SELECT; empty result if schema/feed is unavailable."""
    clock = _utc(now or datetime.now(timezone.utc))
    try:
        with connect(db_path) as db:
            rows = db.execute("""
                SELECT provider_uic, quote_at, received_at, bid, ask
                FROM lsim_hyper_quotes_1s
                WHERE quote_at>=? AND quote_at<=?
                ORDER BY quote_at DESC LIMIT 240
            """, ((clock-timedelta(seconds=120)).isoformat(), clock.isoformat())).fetchall()
    except Exception:
        return []
    return summarize_hyper_quote_window(rows, now=clock)
