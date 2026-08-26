from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from database import connect


SUPPORTED_HORIZONS = (1, 5, 15, 30, 60)
MAX_CANDLE_COUNT = 500


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class ExternalMarketSnapshotV2:
    market: str
    instrument_id: int
    market_id: int
    bar_time: str
    open: float
    high: float
    low: float
    close: float
    volume: float | None
    quality_flags: int
    age_seconds: float
    stale: bool
    source: str = "pricegauger_canonical_v2"
    execution_capability: bool = False


class ExternalMarketReadServiceV2:
    """Read-only boundary for exposing canonical PriceGauger market data.

    This capability deliberately reads persisted v2 market bars only. It never
    imports Saxo authentication or trading modules and cannot place, amend, or
    cancel orders.
    """

    def __init__(
        self,
        db_path: str | Path = "pricegauger.db",
        *,
        stale_after_seconds: int = 180,
        now_fn=_utc_now,
    ) -> None:
        self.db_path = str(db_path)
        self.store = CanonicalMarketBarStoreV2(self.db_path)
        self.stale_after_seconds = max(1, int(stale_after_seconds))
        self._now_fn = now_fn

    def list_markets(self) -> list[dict[str, Any]]:
        with connect(self.db_path) as db:
            rows = db.execute(
                """
                SELECT m.market_id, m.name AS market, i.instrument_id,
                       i.provider, i.provider_instrument_id, i.asset_type
                FROM pg_v2_collection_subscriptions c
                JOIN pg_v2_instruments i
                  ON i.instrument_id=c.instrument_id AND i.active=TRUE
                JOIN pg_v2_markets m
                  ON m.market_id=i.market_id AND m.active=TRUE
                WHERE c.enabled=TRUE
                ORDER BY m.name ASC
                """
            ).fetchall()
        return [
            {
                "market_id": int(row["market_id"]),
                "market": str(row["market"]),
                "instrument_id": int(row["instrument_id"]),
                "provider": str(row["provider"]),
                "provider_instrument_id": str(row["provider_instrument_id"]),
                "asset_type": str(row["asset_type"]),
            }
            for row in rows
        ]

    def snapshot(self, market: str) -> dict[str, Any]:
        name = str(market).strip()
        if not name:
            raise ValueError("market is required")
        bar = self.store.load_latest(market=name)
        if bar is None:
            raise LookupError(f"no canonical v2 market data for {name!r}")
        age_seconds = max(0.0, (self._now_fn() - _parse_utc(bar.bar_time)).total_seconds())
        snapshot = ExternalMarketSnapshotV2(
            market=bar.market_name,
            instrument_id=bar.instrument_id,
            market_id=bar.market_id,
            bar_time=bar.bar_time,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            quality_flags=bar.quality_flags,
            age_seconds=round(age_seconds, 3),
            stale=age_seconds > self.stale_after_seconds,
        )
        return asdict(snapshot)

    def candles(
        self,
        market: str,
        *,
        horizon_minutes: int = 1,
        count: int = 120,
    ) -> dict[str, Any]:
        horizon = int(horizon_minutes)
        if horizon not in SUPPORTED_HORIZONS:
            raise ValueError(f"horizon_minutes must be one of {SUPPORTED_HORIZONS}")
        requested = min(max(int(count), 1), MAX_CANDLE_COUNT)
        end = self._now_fn()
        start = end - timedelta(minutes=horizon * (requested + 3))
        bars = self.store.load_range(
            market=str(market).strip(),
            start=start,
            end=end,
            limit=min(5000, horizon * (requested + 3) + 10),
        )
        aggregated = self._aggregate(bars, horizon)
        selected = aggregated[-requested:]
        return {
            "market": str(market).strip(),
            "horizon_minutes": horizon,
            "count": len(selected),
            "requested_count": requested,
            "source": "pricegauger_canonical_v2",
            "execution_capability": False,
            "candles": selected,
        }

    @staticmethod
    def _aggregate(bars, horizon: int) -> list[dict[str, Any]]:
        buckets: list[dict[str, Any]] = []
        current_key: datetime | None = None
        current: dict[str, Any] | None = None
        for bar in bars:
            stamp = _parse_utc(bar.bar_time)
            minute = (stamp.minute // horizon) * horizon
            bucket = stamp.replace(minute=minute, second=0, microsecond=0)
            if current_key != bucket:
                if current is not None:
                    buckets.append(current)
                current_key = bucket
                current = {
                    "time": bucket.isoformat(),
                    "open": float(bar.open),
                    "high": float(bar.high),
                    "low": float(bar.low),
                    "close": float(bar.close),
                    "volume": None if bar.volume is None else float(bar.volume),
                    "quality_flags": int(bar.quality_flags),
                }
                continue
            assert current is not None
            current["high"] = max(float(current["high"]), float(bar.high))
            current["low"] = min(float(current["low"]), float(bar.low))
            current["close"] = float(bar.close)
            current["quality_flags"] = int(current["quality_flags"]) | int(bar.quality_flags)
            if bar.volume is not None:
                current["volume"] = float(current["volume"] or 0.0) + float(bar.volume)
        if current is not None:
            buckets.append(current)
        return buckets
