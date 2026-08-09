from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from database import connect


def utc(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def minute_start(value: str | datetime) -> datetime:
    stamp = utc(value)
    return stamp.replace(second=0, microsecond=0)


@dataclass(frozen=True, slots=True)
class RealtimeQuote:
    market: str
    observed_at: str
    bid: float | None
    ask: float | None
    last: float | None = None
    provider: str = "Saxo OpenAPI"
    uic: int | None = None
    asset_type: str = ""
    symbol: str = ""

    @property
    def price(self) -> float | None:
        if self.bid is not None and self.ask is not None:
            return (float(self.bid) + float(self.ask)) / 2.0
        if self.last is not None:
            return float(self.last)
        if self.bid is not None:
            return float(self.bid)
        if self.ask is not None:
            return float(self.ask)
        return None


@dataclass(frozen=True, slots=True)
class RealtimeBar1m:
    market: str
    bar_time: str
    open: float
    high: float
    low: float
    close: float
    sample_count: int
    provider: str
    uic: int | None
    asset_type: str
    symbol: str

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class StreamStatus:
    market: str
    updated_at: str
    state: str
    reference_id: str = ""
    requested_refresh_ms: int | None = None
    actual_refresh_ms: int | None = None
    delay_minutes: float | None = None
    last_quote_at: str | None = None
    detail: str = ""

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


class MinuteBarAggregator:
    """Aggregate transient realtime quotes into persistent one-minute OHLC bars."""

    def __init__(self) -> None:
        self._minute: datetime | None = None
        self._market: str | None = None
        self._values: list[float] = []
        self._template: RealtimeQuote | None = None

    def _build(self) -> RealtimeBar1m | None:
        if self._minute is None or not self._values or self._template is None:
            return None
        item = self._template
        return RealtimeBar1m(
            market=item.market,
            bar_time=self._minute.isoformat(),
            open=self._values[0],
            high=max(self._values),
            low=min(self._values),
            close=self._values[-1],
            sample_count=len(self._values),
            provider=item.provider,
            uic=item.uic,
            asset_type=item.asset_type,
            symbol=item.symbol,
        )

    def add(self, quote: RealtimeQuote) -> RealtimeBar1m | None:
        price = quote.price
        if price is None:
            return None
        bucket = minute_start(quote.observed_at)
        if self._market is not None and quote.market != self._market:
            raise ValueError("MinuteBarAggregator instances are single-market")
        self._market = quote.market
        completed: RealtimeBar1m | None = None
        if self._minute is not None and bucket != self._minute:
            if bucket < self._minute:
                return None
            completed = self._build()
            self._values = []
        if self._minute != bucket:
            self._minute = bucket
        self._template = quote
        self._values.append(float(price))
        return completed

    def snapshot(self) -> RealtimeBar1m | None:
        return self._build()


class RealtimeMarketDataStore:
    def __init__(self, path: str | Path = "pricegauger.db") -> None:
        self.path = str(path)
        with connect(self.path) as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS realtime_bars_1m (
                    market TEXT NOT NULL,
                    bar_time TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    uic INTEGER,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (market, bar_time, provider)
                );
                CREATE INDEX IF NOT EXISTS idx_realtime_bars_market_time
                ON realtime_bars_1m(market, bar_time);
                CREATE TABLE IF NOT EXISTS realtime_stream_status (
                    market TEXT PRIMARY KEY,
                    updated_at TEXT NOT NULL,
                    state TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                """
            )

    def save_bar(self, bar: RealtimeBar1m) -> None:
        with connect(self.path) as db:
            db.execute(
                """
                INSERT INTO realtime_bars_1m(market, bar_time, provider, uic, payload_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(market, bar_time, provider) DO UPDATE SET
                    uic=excluded.uic,
                    payload_json=excluded.payload_json,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (bar.market, bar.bar_time, bar.provider, bar.uic, json.dumps(bar.to_record(), sort_keys=True)),
            )

    def save_status(self, status: StreamStatus) -> None:
        with connect(self.path) as db:
            db.execute(
                """
                INSERT INTO realtime_stream_status(market, updated_at, state, payload_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(market) DO UPDATE SET
                    updated_at=excluded.updated_at,
                    state=excluded.state,
                    payload_json=excluded.payload_json
                """,
                (status.market, status.updated_at, status.state, json.dumps(status.to_record(), sort_keys=True)),
            )

    def load_statuses(self) -> list[StreamStatus]:
        with connect(self.path) as db:
            rows = db.execute(
                "SELECT payload_json FROM realtime_stream_status ORDER BY market"
            ).fetchall()
        return [StreamStatus(**json.loads(row["payload_json"])) for row in rows]

    def load_latest_bar(self, *, market: str) -> RealtimeBar1m | None:
        with connect(self.path) as db:
            row = db.execute(
                """
                SELECT payload_json FROM realtime_bars_1m
                WHERE market=?
                ORDER BY bar_time DESC
                LIMIT 1
                """,
                (market,),
            ).fetchone()
        if row is None:
            return None
        return RealtimeBar1m(**json.loads(row["payload_json"]))

    def load_range(self, *, market: str, start: str | datetime, end: str | datetime, limit: int = 10000) -> list[RealtimeBar1m]:
        start_at, end_at = utc(start), utc(end)
        with connect(self.path) as db:
            rows = db.execute(
                """
                SELECT payload_json FROM realtime_bars_1m
                WHERE market=? AND bar_time>=? AND bar_time<=?
                ORDER BY bar_time ASC LIMIT ?
                """,
                (market, start_at.isoformat(), end_at.isoformat(), max(1, int(limit))),
            ).fetchall()
        return [RealtimeBar1m(**json.loads(row["payload_json"])) for row in rows]
