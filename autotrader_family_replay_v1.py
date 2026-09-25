from __future__ import annotations

from datetime import timedelta

import pandas as pd

from autotrader_mtf_entry_shadow_v2 import closed_bars_v2, macd_observations_v2
from autotrader_macd_hist_v1 import histogram_turn_v1
from autotrader_price_macd_v1 import replay_price_macd_v1
from autotrader_price_stoch_v1 import replay_price_stoch_v1
from autotrader_strategy_family_v1 import (
    FAMILY_MACD_V1,
    FAMILY_MACD_HIST_V1,
    FAMILY_PRICE_MACD_V1,
    FAMILY_PRICE_STOCH_V1,
    validate_timeframe_minutes_v1,
)
from canonical_market_bars_v2 import CanonicalMarketBarV2
from trading_desk import utc


def _macd_family_replay_v1(
    bars: tuple[CanonicalMarketBarV2, ...],
    *,
    timeframe_minutes: int,
    histogram_turn: bool = False,
) -> pd.DataFrame:
    minutes = validate_timeframe_minutes_v1(timeframe_minutes)
    if not bars:
        return pd.DataFrame(columns=("PRICE", "TARGET"))

    ordered = tuple(sorted(bars, key=lambda item: utc(item.bar_time)))
    price_index = [pd.Timestamp(utc(item.bar_time) + timedelta(minutes=1)) for item in ordered]
    result = pd.DataFrame(
        {"PRICE": [float(item.close) for item in ordered]},
        index=pd.DatetimeIndex(price_index),
    )

    closed = closed_bars_v2(
        tuple(item.point for item in ordered),
        market=str(ordered[0].market_name),
        timeframe_minutes=minutes,
    )
    observations = macd_observations_v2(closed, timeframe_minutes=minutes)
    crosses: dict[pd.Timestamp, int] = {}
    if histogram_turn:
        for index in range(2, len(observations)):
            turn = histogram_turn_v1(observations[index - 2:index + 1], timeframe_minutes=minutes)
            if turn:
                crosses[pd.Timestamp(observations[index].closed_at)] = 1 if turn == "LONG" else -1
    else:
        for previous, current in zip(observations, observations[1:]):
            if current.closed_at - previous.closed_at != timedelta(minutes=minutes):
                continue
            if previous.spread <= 0.0 < current.spread:
                crosses[pd.Timestamp(current.closed_at)] = 1
            elif previous.spread >= 0.0 > current.spread:
                crosses[pd.Timestamp(current.closed_at)] = -1

    target = 0
    targets: list[int] = []
    for at in result.index:
        if at in crosses:
            target = int(crosses[at])
        targets.append(target)
    result["TARGET"] = pd.Series(targets, index=result.index, dtype="float64")
    return result


def replay_strategy_family_v1(
    bars,
    *,
    family: str,
    timeframe_minutes: int,
) -> pd.DataFrame:
    items = tuple(bars)
    normalized = str(family).strip().upper()
    minutes = validate_timeframe_minutes_v1(timeframe_minutes)
    if normalized == FAMILY_MACD_V1:
        return _macd_family_replay_v1(items, timeframe_minutes=minutes)
    if normalized == FAMILY_MACD_HIST_V1:
        return _macd_family_replay_v1(items, timeframe_minutes=minutes, histogram_turn=True)
    if normalized == FAMILY_PRICE_MACD_V1:
        return replay_price_macd_v1(items, timeframe_minutes=minutes)
    if normalized == FAMILY_PRICE_STOCH_V1:
        if minutes != 1:
            raise ValueError("Price + Stoch v1 currently uses the 1m price/stochastic clock")
        return replay_price_stoch_v1(items)
    raise ValueError(f"unsupported strategy family: {family}")


__all__ = ["replay_strategy_family_v1"]
