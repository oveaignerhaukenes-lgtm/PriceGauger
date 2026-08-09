from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from typing import Iterable

from realtime_market_data import RealtimeBar1m


TIMEFRAME_MINUTES: dict[str, int] = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "1h": 60,
}


@dataclass(frozen=True, slots=True)
class ChartBar:
    """Read-only chart representation derived from canonical completed 1m bars."""

    market: str
    bar_time: str
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None


def utc(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def timeframe_minutes(value: str | int) -> int:
    if isinstance(value, int):
        minutes = value
    else:
        key = str(value).strip().lower()
        if key not in TIMEFRAME_MINUTES:
            raise ValueError(f"Unsupported TradingDesk timeframe: {value}")
        minutes = TIMEFRAME_MINUTES[key]
    if minutes not in TIMEFRAME_MINUTES.values():
        raise ValueError(f"Unsupported TradingDesk timeframe: {value}")
    return minutes


def _finite(value: float, *, field: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Non-finite {field}")
    return number


def _volume(value: float | None) -> float | None:
    if value is None:
        return None
    number = _finite(value, field="volume")
    if number < 0:
        raise ValueError("Negative volume")
    return number


def _as_chart_bar(bar: RealtimeBar1m | ChartBar) -> ChartBar:
    item = ChartBar(
        market=str(bar.market),
        bar_time=utc(bar.bar_time).isoformat(),
        open=_finite(bar.open, field="open"),
        high=_finite(bar.high, field="high"),
        low=_finite(bar.low, field="low"),
        close=_finite(bar.close, field="close"),
        volume=_volume(getattr(bar, "volume", None)),
    )
    if item.high < max(item.open, item.low, item.close):
        raise ValueError(f"Invalid OHLC high at {item.bar_time}")
    if item.low > min(item.open, item.high, item.close):
        raise ValueError(f"Invalid OHLC low at {item.bar_time}")
    return item


def canonical_chart_bars(bars: Iterable[RealtimeBar1m | ChartBar]) -> tuple[ChartBar, ...]:
    """Normalize ordering/UTC and reject conflicting duplicate minute bars."""

    by_stamp: dict[datetime, ChartBar] = {}
    market: str | None = None
    for raw in bars:
        item = _as_chart_bar(raw)
        if market is None:
            market = item.market
        elif item.market != market:
            raise ValueError("TradingDesk chart series must contain one market")
        stamp = utc(item.bar_time)
        previous = by_stamp.get(stamp)
        if previous is not None and previous != item:
            raise ValueError(f"Conflicting duplicate bar at {stamp.isoformat()}")
        by_stamp[stamp] = item
    return tuple(by_stamp[stamp] for stamp in sorted(by_stamp))


def _bucket_start(stamp: datetime, minutes: int) -> datetime:
    bucket_seconds = minutes * 60
    epoch_seconds = int(stamp.timestamp())
    return datetime.fromtimestamp(
        epoch_seconds - (epoch_seconds % bucket_seconds),
        tz=timezone.utc,
    )


def _has_complete_minute_coverage(items: list[ChartBar], *, bucket: datetime, minutes: int) -> bool:
    observed = {utc(item.bar_time) for item in items}
    expected = {bucket + timedelta(minutes=offset) for offset in range(minutes)}
    return observed == expected


def resample_bars(
    bars: Iterable[RealtimeBar1m | ChartBar],
    *,
    timeframe: str | int,
) -> tuple[ChartBar, ...]:
    """Resample canonical completed 1m OHLCV without fabricating missing minutes.

    OHLC uses the observed completed bars only. Aggregated volume is stricter: it
    is emitted only when the bucket has every expected 1m bar and every one of
    those bars carries real market volume. Missing minutes therefore make volume
    unknown instead of silently understating traded volume.
    """

    minutes = timeframe_minutes(timeframe)
    source = canonical_chart_bars(bars)
    if not source:
        return ()

    buckets: dict[datetime, list[ChartBar]] = {}
    for item in source:
        bucket = _bucket_start(utc(item.bar_time), minutes)
        buckets.setdefault(bucket, []).append(item)

    result: list[ChartBar] = []
    for bucket in sorted(buckets):
        items = buckets[bucket]
        volumes = [item.volume for item in items]
        complete_coverage = _has_complete_minute_coverage(items, bucket=bucket, minutes=minutes)
        volume = (
            sum(float(value) for value in volumes if value is not None)
            if complete_coverage and all(value is not None for value in volumes)
            else None
        )
        result.append(
            ChartBar(
                market=items[0].market,
                bar_time=bucket.isoformat(),
                open=items[0].open,
                high=max(item.high for item in items),
                low=min(item.low for item in items),
                close=items[-1].close,
                volume=volume,
            )
        )
    return tuple(result)


def close_series(bars: Iterable[RealtimeBar1m | ChartBar]) -> tuple[tuple[str, float], ...]:
    return tuple((item.bar_time, item.close) for item in canonical_chart_bars(bars))


def normalized_close_series(
    bars: Iterable[RealtimeBar1m | ChartBar],
) -> tuple[tuple[str, float], ...]:
    """Return close prices indexed to 100 at the first available point."""

    series = close_series(bars)
    if not series:
        return ()
    baseline = float(series[0][1])
    if baseline == 0.0:
        raise ValueError("Cannot normalize a zero-price series")
    return tuple((stamp, float(price) / baseline * 100.0) for stamp, price in series)
