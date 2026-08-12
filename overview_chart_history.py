from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from database import connect


# The chart should expose enough history to reveal regime adaptation without
# repeatedly reading months of canonical 1m bars in the five-second Overview
# fragment. Older context therefore comes from sparse technical snapshots while
# the recent edge retains canonical 1m resolution.
_HISTORY_DAYS_BY_HORIZON = (
    (5.0 / 60.0, 7),
    (15.0 / 60.0, 14),
    (0.5, 30),
    (1.0, 30),
    (4.0, 90),
    (12.0, 180),
    (24.0, 180),
    (168.0, 365),
)


def history_days_for_horizon(horizon_hours: float) -> int:
    value = float(horizon_hours)
    return min(_HISTORY_DAYS_BY_HORIZON, key=lambda item: abs(item[0] - value))[1]


def _utc(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _sample(points: list[tuple[datetime, float]], limit: int) -> list[tuple[datetime, float]]:
    max_points = max(2, int(limit))
    if len(points) <= max_points:
        return points
    # Deterministic even spacing, retaining both endpoints. This is display-only;
    # canonical bars in storage remain untouched.
    last = len(points) - 1
    indexes = sorted({round(index * last / (max_points - 1)) for index in range(max_points)})
    return [points[index] for index in indexes]


def load_overview_chart_history(
    path: str | Path,
    *,
    market: str,
    as_of: str | datetime,
    horizon_hours: float,
    technical_limit: int = 900,
    recent_1m_hours: float = 36.0,
    recent_1m_limit: int = 900,
) -> tuple[tuple[str, float], ...]:
    """Return a bounded long-history chart series for Overview.

    Historical context is sampled from technical-state snapshots over a horizon-
    appropriate calendar span. The most recent edge is replaced by canonical 1m
    closes, sampled only for display. This avoids a months-long 1m query on every
    live-card refresh while preserving the authoritative recent price path.
    """
    end = _utc(as_of)
    start = end - timedelta(days=history_days_for_horizon(horizon_hours))
    recent_start = max(start, end - timedelta(hours=max(1.0, float(recent_1m_hours))))

    technical: list[tuple[datetime, float]] = []
    realtime: list[tuple[datetime, float]] = []
    try:
        with connect(path) as db:
            rows = db.execute(
                """
                SELECT payload_json
                FROM technical_market_state_snapshots
                WHERE market=? AND as_of>=? AND as_of<=?
                ORDER BY as_of ASC
                """,
                (str(market), start.isoformat(), end.isoformat()),
            ).fetchall()
        parsed: list[tuple[datetime, float]] = []
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
                stamp = _utc(str(payload.get("as_of") or ""))
                price = payload.get("price")
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if price is not None:
                parsed.append((stamp, float(price)))
        technical = _sample(parsed, technical_limit)
    except Exception:
        technical = []

    try:
        with connect(path) as db:
            rows = db.execute(
                """
                SELECT payload_json
                FROM realtime_bars_1m
                WHERE market=? AND bar_time>=? AND bar_time<=?
                ORDER BY bar_time ASC
                """,
                (str(market), recent_start.isoformat(), end.isoformat()),
            ).fetchall()
        parsed = []
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
                stamp = _utc(str(payload.get("bar_time") or ""))
                price = payload.get("close")
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if price is not None:
                parsed.append((stamp, float(price)))
        realtime = _sample(parsed, recent_1m_limit)
    except Exception:
        realtime = []

    merged: dict[datetime, float] = {stamp: price for stamp, price in technical}
    # Canonical 1m observations win if a sparse technical snapshot shares a stamp.
    merged.update({stamp: price for stamp, price in realtime})
    points = sorted(merged.items(), key=lambda item: item[0])
    return tuple((stamp.isoformat(), price) for stamp, price in points)
