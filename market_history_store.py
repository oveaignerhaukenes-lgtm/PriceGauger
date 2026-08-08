from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from database import connect


class MarketHistoryStore:
    """Read coarse real price history from persisted technical market states.

    Forecast charts should compare their horizon with the same amount of *active*
    market history. Closed-market gaps (weekends/session breaks/provider pauses)
    therefore do not consume the requested history window.
    """

    def __init__(self, path: str | Path = "pricegauger.db") -> None:
        self.path = str(path)

    @staticmethod
    def _parse_stamp(value: str) -> datetime | None:
        try:
            observed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        return observed.astimezone(timezone.utc)

    def load_window(
        self,
        *,
        market: str,
        as_of: str,
        horizon_hours: float,
        limit: int = 2000,
        max_active_gap_minutes: float = 30.0,
    ) -> tuple[tuple[str, float], ...]:
        end = self._parse_stamp(as_of)
        if end is None:
            return ()

        target_seconds = max(0.25, float(horizon_hours)) * 3600.0
        max_active_gap_seconds = max(60.0, float(max_active_gap_minutes) * 60.0)

        with connect(self.path) as db:
            rows = db.execute(
                """
                SELECT payload_json
                FROM technical_market_state_snapshots
                WHERE market=? AND as_of<=?
                ORDER BY as_of DESC
                LIMIT ?
                """,
                (market, end.isoformat(), max(2, int(limit))),
            ).fetchall()

        parsed: list[tuple[datetime, float]] = []
        for row in rows:
            record = json.loads(row["payload_json"])
            price = record.get("price")
            observed = self._parse_stamp(str(record.get("as_of") or ""))
            if price is None or observed is None or observed > end:
                continue
            parsed.append((observed, float(price)))

        if not parsed:
            return ()

        # Rows arrive newest-first. Walk backwards and count only intervals that
        # look like continuous trading. Large gaps are preserved semantically as
        # market/data gaps, but do not consume the requested active-history span.
        parsed.sort(key=lambda item: item[0], reverse=True)
        selected: list[tuple[datetime, float]] = [parsed[0]]
        active_seconds = 0.0
        cursor = parsed[0][0]
        for point in parsed[1:]:
            observed = point[0]
            gap_seconds = max(0.0, (cursor - observed).total_seconds())
            if gap_seconds <= max_active_gap_seconds:
                active_seconds += gap_seconds
            selected.append(point)
            cursor = observed
            if active_seconds >= target_seconds:
                break

        selected.reverse()
        return tuple((stamp.isoformat(), price) for stamp, price in selected)
