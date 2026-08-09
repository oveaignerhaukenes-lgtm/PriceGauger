from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math

from trading_desk import timeframe_minutes, utc


@dataclass(frozen=True, slots=True)
class CandleCountdown:
    seconds_remaining: int
    next_boundary: datetime

    @property
    def label(self) -> str:
        hours, remainder = divmod(self.seconds_remaining, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"


def candle_countdown(now: datetime | str, *, timeframe: str | int) -> CandleCountdown:
    """Return time until the next canonical UTC candle boundary.

    TradingDesk candles are bucketed on UTC epoch boundaries, so this helper uses
    the exact same alignment. The value is a wall-clock countdown only; it does not
    imply that Saxo/PriceGauger has persisted the completed candle at that instant.
    """

    current = utc(now)
    interval_seconds = timeframe_minutes(timeframe) * 60
    timestamp = current.timestamp()
    next_epoch = (math.floor(timestamp / interval_seconds) + 1) * interval_seconds
    remaining = max(1, math.ceil(next_epoch - timestamp))
    return CandleCountdown(
        seconds_remaining=remaining,
        next_boundary=datetime.fromtimestamp(next_epoch, tz=timezone.utc),
    )
