from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from database import connect


class MarketHistoryStore:
    """Read canonical market-price history with backwards-compatible fallback.

    One-minute bars produced by ``pricegauger-stream`` are the preferred source.
    Older technical-state snapshots remain available for historical continuity and
    fill periods for which realtime bars do not exist. When both sources contain
    the same timestamp, the realtime bar wins.

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

    @staticmethod
    def _normalized_range(
        start: str | datetime, end: str | datetime
    ) -> tuple[datetime, datetime] | None:
        parse = MarketHistoryStore._parse_stamp
        start_at = start if isinstance(start, datetime) else parse(str(start))
        end_at = end if isinstance(end, datetime) else parse(str(end))
        if start_at is None or end_at is None:
            return None
        if start_at.tzinfo is None:
            start_at = start_at.replace(tzinfo=timezone.utc)
        if end_at.tzinfo is None:
            end_at = end_at.replace(tzinfo=timezone.utc)
        start_at = start_at.astimezone(timezone.utc)
        end_at = end_at.astimezone(timezone.utc)
        if end_at < start_at:
            start_at, end_at = end_at, start_at
        return start_at, end_at

    def _technical_range(
        self, *, market: str, start_at: datetime, end_at: datetime, limit: int
    ) -> list[tuple[datetime, float]]:
        try:
            with connect(self.path) as db:
                rows = db.execute(
                    """
                    SELECT payload_json
                    FROM technical_market_state_snapshots
                    WHERE market=? AND as_of>=? AND as_of<=?
                    ORDER BY as_of ASC
                    LIMIT ?
                    """,
                    (market, start_at.isoformat(), end_at.isoformat(), max(1, int(limit))),
                ).fetchall()
        except Exception:
            return []

        points: list[tuple[datetime, float]] = []
        for row in rows:
            try:
                record = json.loads(row["payload_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            price = record.get("price")
            observed = self._parse_stamp(str(record.get("as_of") or ""))
            if price is None or observed is None:
                continue
            points.append((observed, float(price)))
        return points

    def _realtime_range(
        self, *, market: str, start_at: datetime, end_at: datetime, limit: int
    ) -> list[tuple[datetime, float]]:
        try:
            with connect(self.path) as db:
                rows = db.execute(
                    """
                    SELECT payload_json
                    FROM realtime_bars_1m
                    WHERE market=? AND bar_time>=? AND bar_time<=?
                    ORDER BY bar_time ASC
                    LIMIT ?
                    """,
                    (market, start_at.isoformat(), end_at.isoformat(), max(1, int(limit))),
                ).fetchall()
        except Exception:
            return []

        points: list[tuple[datetime, float]] = []
        for row in rows:
            try:
                record = json.loads(row["payload_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            price = record.get("close")
            observed = self._parse_stamp(str(record.get("bar_time") or ""))
            if price is None or observed is None:
                continue
            points.append((observed, float(price)))
        return points

    @staticmethod
    def _merge_points(
        technical: list[tuple[datetime, float]],
        realtime: list[tuple[datetime, float]],
        *,
        reverse: bool = False,
        limit: int | None = None,
    ) -> list[tuple[datetime, float]]:
        # Load technical history first so canonical realtime bars replace matching
        # timestamps rather than producing duplicates.
        merged: dict[datetime, float] = {stamp: price for stamp, price in technical}
        merged.update({stamp: price for stamp, price in realtime})
        result = sorted(merged.items(), key=lambda item: item[0], reverse=reverse)
        if limit is not None:
            result = result[: max(1, int(limit))]
        return result

    def load_range(
        self,
        *,
        market: str,
        start: str | datetime,
        end: str | datetime,
        limit: int = 5000,
    ) -> tuple[tuple[str, float], ...]:
        normalized = self._normalized_range(start, end)
        if normalized is None:
            return ()
        start_at, end_at = normalized
        max_rows = max(1, int(limit))
        points = self._merge_points(
            self._technical_range(
                market=market, start_at=start_at, end_at=end_at, limit=max_rows
            ),
            self._realtime_range(
                market=market, start_at=start_at, end_at=end_at, limit=max_rows
            ),
            limit=max_rows,
        )
        return tuple((stamp.isoformat(), price) for stamp, price in points)

    def load_since(
        self,
        *,
        market: str,
        start: str | datetime,
        limit: int = 10000,
    ) -> tuple[tuple[str, float], ...]:
        start_at = start if isinstance(start, datetime) else self._parse_stamp(str(start))
        if start_at is None:
            return ()
        if start_at.tzinfo is None:
            start_at = start_at.replace(tzinfo=timezone.utc)
        start_at = start_at.astimezone(timezone.utc)
        # ISO timestamps sort chronologically in the persisted UTC representation;
        # use a distant UTC ceiling without imposing current-time lookahead logic.
        end_at = datetime.max.replace(tzinfo=timezone.utc)
        return self.load_range(
            market=market,
            start=start_at,
            end=end_at,
            limit=limit,
        )

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
        max_rows = max(2, int(limit))

        try:
            with connect(self.path) as db:
                technical_rows = db.execute(
                    """
                    SELECT payload_json
                    FROM technical_market_state_snapshots
                    WHERE market=? AND as_of<=?
                    ORDER BY as_of DESC
                    LIMIT ?
                    """,
                    (market, end.isoformat(), max_rows),
                ).fetchall()
        except Exception:
            technical_rows = []

        technical: list[tuple[datetime, float]] = []
        for row in technical_rows:
            try:
                record = json.loads(row["payload_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            price = record.get("price")
            observed = self._parse_stamp(str(record.get("as_of") or ""))
            if price is None or observed is None or observed > end:
                continue
            technical.append((observed, float(price)))

        try:
            with connect(self.path) as db:
                realtime_rows = db.execute(
                    """
                    SELECT payload_json
                    FROM realtime_bars_1m
                    WHERE market=? AND bar_time<=?
                    ORDER BY bar_time DESC
                    LIMIT ?
                    """,
                    (market, end.isoformat(), max_rows),
                ).fetchall()
        except Exception:
            realtime_rows = []

        realtime: list[tuple[datetime, float]] = []
        for row in realtime_rows:
            try:
                record = json.loads(row["payload_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            price = record.get("close")
            observed = self._parse_stamp(str(record.get("bar_time") or ""))
            if price is None or observed is None or observed > end:
                continue
            realtime.append((observed, float(price)))

        parsed = self._merge_points(
            technical,
            realtime,
            reverse=True,
            limit=max_rows,
        )
        if not parsed:
            return ()

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
