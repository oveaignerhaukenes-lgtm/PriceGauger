from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from database import connect


class MarketHistoryStore:
    """Read coarse real price history from persisted technical market states."""

    def __init__(self, path: str | Path = "pricegauger.db") -> None:
        self.path = str(path)

    def load_window(
        self,
        *,
        market: str,
        as_of: str,
        horizon_hours: float,
        limit: int = 200,
    ) -> tuple[tuple[str, float], ...]:
        try:
            end = datetime.fromisoformat(str(as_of).replace("Z", "+00:00"))
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            start = end.astimezone(timezone.utc) - timedelta(hours=max(0.25, float(horizon_hours)))
        except (TypeError, ValueError):
            return ()

        with connect(self.path) as db:
            rows = db.execute(
                """
                SELECT payload_json
                FROM technical_market_state_snapshots
                WHERE market=? AND as_of<=?
                ORDER BY as_of DESC
                LIMIT ?
                """,
                (market, end.astimezone(timezone.utc).isoformat(), max(2, int(limit))),
            ).fetchall()

        points: list[tuple[str, float]] = []
        for row in reversed(rows):
            record = json.loads(row["payload_json"])
            price = record.get("price")
            stamp = str(record.get("as_of") or "")
            if price is None or not stamp:
                continue
            try:
                observed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                if observed.tzinfo is None:
                    observed = observed.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if observed.astimezone(timezone.utc) >= start:
                points.append((observed.astimezone(timezone.utc).isoformat(), float(price)))
        return tuple(points)
