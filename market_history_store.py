from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from database import connect, using_postgres


class MarketHistoryStore:
    """Canonical market-price history reader.

    PostgreSQL v2 bars are authoritative when available. Legacy realtime bars and
    older technical snapshots remain bounded fallback sources during AP13 so an
    empty pre-cutover range does not erase historical continuity.
    """

    def __init__(self, path: str | Path = "pricegauger.db") -> None:
        self.path = str(path)

    @staticmethod
    def _parse_stamp(value) -> datetime | None:
        try:
            observed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        return observed.astimezone(timezone.utc)

    @staticmethod
    def _normalized_range(start, end):
        start_at = MarketHistoryStore._parse_stamp(start)
        end_at = MarketHistoryStore._parse_stamp(end)
        if start_at is None or end_at is None:
            return None
        return (end_at, start_at) if end_at < start_at else (start_at, end_at)

    def _technical_range(self, *, market, start_at, end_at, limit):
        try:
            with connect(self.path) as db:
                rows = db.execute("SELECT payload_json FROM technical_market_state_snapshots WHERE market=? AND as_of>=? AND as_of<=? ORDER BY as_of ASC LIMIT ?", (market,start_at.isoformat(),end_at.isoformat(),max(1,int(limit)))).fetchall()
        except Exception:
            return []
        result=[]
        for row in rows:
            try: record=json.loads(row["payload_json"])
            except (TypeError,json.JSONDecodeError): continue
            stamp=self._parse_stamp(record.get("as_of")); price=record.get("price")
            if stamp is not None and price is not None: result.append((stamp,float(price)))
        return result

    def _legacy_realtime_range(self, *, market, start_at, end_at, limit):
        try:
            with connect(self.path) as db:
                rows=db.execute("SELECT payload_json FROM realtime_bars_1m WHERE market=? AND bar_time>=? AND bar_time<=? ORDER BY bar_time ASC LIMIT ?",(market,start_at.isoformat(),end_at.isoformat(),max(1,int(limit)))).fetchall()
        except Exception:
            return []
        result=[]
        for row in rows:
            try: record=json.loads(row["payload_json"])
            except (TypeError,json.JSONDecodeError): continue
            stamp=self._parse_stamp(record.get("bar_time")); price=record.get("close")
            if stamp is not None and price is not None: result.append((stamp,float(price)))
        return result

    def _v2_range(self, *, market, start_at, end_at, limit):
        if not using_postgres():
            return []
        try:
            from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
            return [(self._parse_stamp(item.bar_time), item.close) for item in CanonicalMarketBarStoreV2(self.path).load_range(market=market,start=start_at,end=end_at,limit=limit)]
        except Exception:
            return []

    @staticmethod
    def _merge_points(*sources, reverse=False, limit=None):
        merged={}
        for source in sources:
            merged.update({stamp:price for stamp,price in source if stamp is not None})
        result=sorted(merged.items(),key=lambda item:item[0],reverse=reverse)
        return result if limit is None else result[:max(1,int(limit))]

    def load_range(self, *, market, start, end, limit=5000):
        normalized=self._normalized_range(start,end)
        if normalized is None: return ()
        start_at,end_at=normalized; max_rows=max(1,int(limit))
        points=self._merge_points(
            self._technical_range(market=market,start_at=start_at,end_at=end_at,limit=max_rows),
            self._legacy_realtime_range(market=market,start_at=start_at,end_at=end_at,limit=max_rows),
            self._v2_range(market=market,start_at=start_at,end_at=end_at,limit=max_rows),
            limit=max_rows,
        )
        return tuple((stamp.isoformat(),price) for stamp,price in points)

    def load_since(self, *, market, start, limit=10000):
        start_at=self._parse_stamp(start)
        if start_at is None: return ()
        return self.load_range(market=market,start=start_at,end=datetime.max.replace(tzinfo=timezone.utc),limit=limit)

    def load_window(self, *, market, as_of, horizon_hours, limit=2000, max_active_gap_minutes=30.0):
        end=self._parse_stamp(as_of)
        if end is None: return ()
        max_rows=max(2,int(limit))
        # Pull a deliberately generous wall-clock range, then count only active gaps.
        # 30 days covers weekends/session closures while preserving the old active-time semantics.
        from datetime import timedelta
        parsed=[(self._parse_stamp(stamp),price) for stamp,price in self.load_range(market=market,start=end-timedelta(days=30),end=end,limit=max_rows)]
        parsed=[item for item in parsed if item[0] is not None and item[0] <= end]
        parsed.sort(key=lambda item:item[0],reverse=True)
        if not parsed: return ()
        target_seconds=max(0.25,float(horizon_hours))*3600.0
        max_gap=max(60.0,float(max_active_gap_minutes)*60.0)
        selected=[parsed[0]]; active=0.0; cursor=parsed[0][0]
        for point in parsed[1:]:
            gap=max(0.0,(cursor-point[0]).total_seconds())
            if gap <= max_gap: active += gap
            selected.append(point); cursor=point[0]
            if active >= target_seconds: break
        selected.reverse()
        return tuple((stamp.isoformat(),price) for stamp,price in selected)
