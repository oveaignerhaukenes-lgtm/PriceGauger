from __future__ import annotations

from typing import Iterable

import pandas as pd

from autotrader_macd_timeframe_policy_v2 import SUPPORTED_MACD_TIMEFRAME_MINUTES
from timeframe_contract_v2 import normalize_canonical_1m_v2
from trading_desk import ChartBar


def normalize_macd_timeframe_minutes_v2(value: int) -> int:
    minutes = int(value)
    if minutes not in SUPPORTED_MACD_TIMEFRAME_MINUTES:
        raise ValueError("MACD timeframe must be 5, 15 or 30 minutes")
    return minutes


def closed_macd_bars_v2(
    points: Iterable[tuple[str, float]],
    *,
    market: str,
    timeframe_minutes: int,
) -> tuple[ChartBar, ...]:
    """Build only fully closed epoch-aligned MACD bars from canonical 1m observations.

    Forming buckets are never exposed to strategy logic and missing canonical minutes
    are never forward-filled. Supported strategy timeframes are deliberately bounded
    to 5m, 15m and 30m for the first AutoManager capability.
    """
    minutes = normalize_macd_timeframe_minutes_v2(timeframe_minutes)
    one = normalize_canonical_1m_v2(points)
    latest = one["timestamp"].iloc[-1]
    observed_through = latest.floor("min") + pd.Timedelta(minutes=1)
    rule = f"{minutes}min"
    aggregated = (
        one.set_index("timestamp")
        .resample(rule, label="left", closed="left", origin="epoch")
        .agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"))
        .dropna(subset=["close"])
    )
    if aggregated.empty:
        return ()
    aggregated = aggregated.loc[(aggregated.index + pd.Timedelta(minutes=minutes)) <= observed_through]
    bars: list[ChartBar] = []
    for stamp, row in aggregated.iterrows():
        bars.append(
            ChartBar(
                market=market,
                bar_time=stamp.to_pydatetime().isoformat(),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=None,
            )
        )
    return tuple(bars)


__all__ = ["closed_macd_bars_v2", "normalize_macd_timeframe_minutes_v2"]
