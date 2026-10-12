"""Lightweight, read-only canonical closed-bar watcher for V3 LIVE.

One indexed-range SQL read each second, no Saxo REST calls on idle ticks.
Wakes the heavyweight broker-safe V3 cycle for a NEW closed 1m bar, while
the ordinary reconciliation heartbeat remains every 30 seconds.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from database import connect


def closed_instrument_cursors_v3(
    *, db_path: str | Path = "pricegauger.db", now: datetime | None = None,
) -> tuple[tuple[int, str], ...]:
    """Read recent, *fully closed* physical Saxo 1m bars by instrument identity.

    We deliberately do not trigger from quotes or a still-forming bar.
    The last ten minutes bound scan cost and allow an empty result while
    the market is closed; full inventory reconciliation still runs on its
    independent, time-based cadence. Reads no account credentials or orders.
    """
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    minute = instant.astimezone(timezone.utc).replace(second=0, microsecond=0)
    lower = minute - timedelta(minutes=10)
    with connect(db_path) as db:
        rows = db.execute(
            """SELECT instrument_id, MAX(bar_time) AS last_closed
               FROM pg_v2_market_bars_1m
               WHERE bar_time>=? AND bar_time<?
               GROUP BY instrument_id
               ORDER BY instrument_id""",
            (lower, minute),
        ).fetchall()
    return tuple(
        (int(row["instrument_id"]), str(row["last_closed"]))
        for row in rows if row["last_closed"] is not None
    )


def has_new_closed_bar_v3(previous, current) -> bool:
    """No work on an unchanged or empty feed; wake once on real progress.

    Newly-enrolled instruments and newly-closed bars both wake the cycle.
    Dropping a stale instrument from the ten-minute window does not.
    """
    old = {instrument:stamp for instrument,stamp in (previous or ())}
    return any(stamp != old.get(instrument) for instrument,stamp in current)
