from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from database import connect


def _as_utc(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def load_rollover_marker_events_v1(*, market: str, limit: int = 20) -> tuple[dict[str, Any], ...]:
    """Read audited rollover boundaries for chart presentation only."""

    name = str(market or "").strip()
    if not name:
        return ()
    with connect() as db:
        rows = db.execute(
            """
            SELECT r.occurred_at, r.old_provider_instrument_id, r.new_provider_instrument_id,
                   r.old_symbol, r.new_symbol, r.reason
            FROM pg_v2_instrument_rollovers r
            JOIN pg_v2_markets m ON m.market_id = r.market_id
            WHERE m.name = ?
            ORDER BY r.occurred_at DESC, r.rollover_id DESC
            LIMIT ?
            """,
            (name, max(1, min(int(limit), 200))),
        ).fetchall()
    events: list[dict[str, Any]] = []
    for row in rows:
        get = lambda key, index: row[key] if isinstance(row, dict) else row[index]
        occurred_at = _as_utc(get("occurred_at", 0))
        if occurred_at is None:
            continue
        events.append(
            {
                "occurred_at": occurred_at,
                "old_uic": str(get("old_provider_instrument_id", 1)),
                "new_uic": str(get("new_provider_instrument_id", 2)),
                "old_symbol": str(get("old_symbol", 3) or "") or None,
                "new_symbol": str(get("new_symbol", 4) or "") or None,
                "reason": str(get("reason", 5) or ""),
            }
        )
    return tuple(events)


__all__ = ["load_rollover_marker_events_v1"]
