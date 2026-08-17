from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from database import connect
from instrument_registry_v2 import InstrumentSourceV2, resolve_instrument_source_v2
from realtime_market_data import RealtimeBar1m


QUALITY_REALTIME = 1
QUALITY_BACKFILL = 2


def _utc(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class CanonicalMarketBarV2:
    instrument_id: int
    market_id: int
    market_name: str
    bar_time: str
    open: float
    high: float
    low: float
    close: float
    volume: float | None
    quality_flags: int

    @property
    def point(self) -> tuple[str, float]:
        return self.bar_time, self.close


class CanonicalMarketBarStoreV2:
    """Canonical physical 1m storage keyed by v2 instrument identity."""

    def __init__(self, path: str | Path = "pricegauger.db") -> None:
        self.path = str(path)

    def save(self, *, source: InstrumentSourceV2, bar: RealtimeBar1m, quality_flags: int) -> None:
        if source.market_name != bar.market:
            raise ValueError("bar market does not match canonical v2 source")
        if source.provider.strip().lower() != "saxo":
            raise ValueError("canonical realtime bar cutover currently requires Saxo source")
        if str(source.provider_instrument_id) != str(bar.uic):
            raise ValueError("bar UIC does not match canonical v2 source")
        stamp = _utc(bar.bar_time)
        with connect(self.path) as db:
            db.execute(
                """
                INSERT INTO pg_v2_market_bars_1m(
                    instrument_id, bar_time, open, high, low, close, volume, quality_flags
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(instrument_id, bar_time) DO UPDATE SET
                    open=excluded.open,
                    high=excluded.high,
                    low=excluded.low,
                    close=excluded.close,
                    volume=excluded.volume,
                    quality_flags=excluded.quality_flags
                """,
                (
                    int(source.instrument_id), stamp, float(bar.open), float(bar.high),
                    float(bar.low), float(bar.close), None if bar.volume is None else float(bar.volume),
                    int(quality_flags),
                ),
            )

    def save_saxo_bar(self, bar: RealtimeBar1m, *, quality_flags: int = QUALITY_REALTIME) -> None:
        if bar.uic is None:
            raise ValueError("canonical v2 bar requires provider instrument identity")
        source = resolve_instrument_source_v2(
            provider="saxo",
            provider_instrument_id=str(bar.uic),
            require_subscription=True,
        )
        self.save(source=source, bar=bar, quality_flags=quality_flags)

    def load_range(
        self,
        *,
        market: str,
        start: str | datetime,
        end: str | datetime,
        limit: int = 5000,
    ) -> tuple[CanonicalMarketBarV2, ...]:
        start_at, end_at = _utc(start), _utc(end)
        if end_at < start_at:
            start_at, end_at = end_at, start_at
        with connect(self.path) as db:
            rows = db.execute(
                """
                SELECT b.instrument_id, i.market_id, m.name AS market_name, b.bar_time,
                       b.open, b.high, b.low, b.close, b.volume, COALESCE(b.quality_flags, 0) AS quality_flags
                FROM pg_v2_market_bars_1m b
                JOIN pg_v2_instruments i ON i.instrument_id=b.instrument_id AND i.active=TRUE
                JOIN pg_v2_markets m ON m.market_id=i.market_id AND m.active=TRUE
                JOIN pg_v2_collection_subscriptions c ON c.instrument_id=i.instrument_id AND c.enabled=TRUE
                WHERE m.name=? AND b.bar_time>=? AND b.bar_time<=?
                ORDER BY b.bar_time ASC
                LIMIT ?
                """,
                (market, start_at, end_at, max(1, int(limit))),
            ).fetchall()
        return tuple(
            CanonicalMarketBarV2(
                instrument_id=int(row["instrument_id"]), market_id=int(row["market_id"]),
                market_name=str(row["market_name"]), bar_time=_utc(row["bar_time"]).isoformat(),
                open=float(row["open"]), high=float(row["high"]), low=float(row["low"]), close=float(row["close"]),
                volume=None if row["volume"] is None else float(row["volume"]), quality_flags=int(row["quality_flags"]),
            )
            for row in rows
        )

    def load_latest(self, *, market: str) -> CanonicalMarketBarV2 | None:
        with connect(self.path) as db:
            row = db.execute(
                """
                SELECT b.instrument_id, i.market_id, m.name AS market_name, b.bar_time,
                       b.open, b.high, b.low, b.close, b.volume, COALESCE(b.quality_flags, 0) AS quality_flags
                FROM pg_v2_market_bars_1m b
                JOIN pg_v2_instruments i ON i.instrument_id=b.instrument_id AND i.active=TRUE
                JOIN pg_v2_markets m ON m.market_id=i.market_id AND m.active=TRUE
                JOIN pg_v2_collection_subscriptions c ON c.instrument_id=i.instrument_id AND c.enabled=TRUE
                WHERE m.name=?
                ORDER BY b.bar_time DESC
                LIMIT 1
                """,
                (market,),
            ).fetchone()
        if row is None:
            return None
        return CanonicalMarketBarV2(
            instrument_id=int(row["instrument_id"]), market_id=int(row["market_id"]), market_name=str(row["market_name"]),
            bar_time=_utc(row["bar_time"]).isoformat(), open=float(row["open"]), high=float(row["high"]),
            low=float(row["low"]), close=float(row["close"]), volume=None if row["volume"] is None else float(row["volume"]),
            quality_flags=int(row["quality_flags"]),
        )
