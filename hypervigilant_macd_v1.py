from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from autotrader_mtf_entry_shadow_v2 import MtfObservationV2, closed_bars_v2, macd_observations_v2
from trading_desk import ChartBar


MACD_HYPERVIGILANT_VERSION_V1 = "macd-hypervigilant-close-v1"


@dataclass(frozen=True, slots=True)
class HypervigilantMacdSampleV1:
    sampled_at: datetime
    bucket_start: datetime
    macd: float
    signal: float
    spread: float


def _utc(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def bucket_start_v1(value: datetime | str, *, timeframe_minutes: int) -> datetime:
    stamp = _utc(value).replace(second=0, microsecond=0)
    minutes = int(timeframe_minutes)
    if minutes <= 0:
        raise ValueError("timeframe_minutes must be positive")
    epoch_minutes = int(stamp.timestamp() // 60)
    bucket_epoch_minutes = epoch_minutes - (epoch_minutes % minutes)
    return datetime.fromtimestamp(bucket_epoch_minutes * 60, tz=timezone.utc)


def materialize_hypervigilant_macd_v1(
    points: Iterable[tuple[str, float]],
    *,
    market: str,
    timeframe_minutes: int,
    forming_bar_time: datetime | str,
    forming_close: float,
) -> tuple[MtfObservationV2, ...]:
    """Return the exact MACD state for completed buckets plus the live provisional bucket.

    MACD is defined on timeframe closes. Completed timeframe buckets are derived from
    canonical exact-instrument 1m closes. The currently forming timeframe bucket is
    appended once with the latest Saxo forming close, so changing the price inside the
    bucket changes that one provisional close rather than inventing extra MACD periods.

    This is the shared semantic used by simple LIVE execution and TradingDesk display.
    It deliberately does not wait for candle close and does not debounce/confirm crosses.
    """
    minutes = int(timeframe_minutes)
    source_time = _utc(forming_bar_time).replace(second=0, microsecond=0)
    bucket = bucket_start_v1(source_time, timeframe_minutes=minutes)
    closed = closed_bars_v2(tuple(points), market=market, timeframe_minutes=minutes)
    completed_before_current = tuple(item for item in closed if _utc(item.bar_time) < bucket)
    price = float(forming_close)
    current = ChartBar(
        market=str(market),
        bar_time=bucket.isoformat(),
        open=price,
        high=price,
        low=price,
        close=price,
        volume=None,
    )
    return macd_observations_v2(
        completed_before_current + (current,),
        timeframe_minutes=minutes,
    )


def latest_hypervigilant_macd_sample_v1(
    points: Iterable[tuple[str, float]],
    *,
    market: str,
    timeframe_minutes: int,
    forming_bar_time: datetime | str,
    forming_close: float,
    sampled_at: datetime | str,
) -> HypervigilantMacdSampleV1:
    observations = materialize_hypervigilant_macd_v1(
        points,
        market=market,
        timeframe_minutes=timeframe_minutes,
        forming_bar_time=forming_bar_time,
        forming_close=forming_close,
    )
    if not observations:
        raise ValueError(f"MACD {int(timeframe_minutes)}m hyper-vigilant clock needs enough history")
    current = observations[-1]
    return HypervigilantMacdSampleV1(
        sampled_at=_utc(sampled_at),
        bucket_start=_utc(current.bar_time),
        macd=float(current.macd),
        signal=float(current.signal),
        spread=float(current.spread),
    )


__all__ = [
    "MACD_HYPERVIGILANT_VERSION_V1",
    "HypervigilantMacdSampleV1",
    "bucket_start_v1",
    "latest_hypervigilant_macd_sample_v1",
    "materialize_hypervigilant_macd_v1",
]
