from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

import pandas as pd


@dataclass(frozen=True, slots=True)
class TimeframeSpecV2:
    name: str
    rule: str


DEFAULT_TIMEFRAME_SPECS_V2: tuple[TimeframeSpecV2, ...] = (
    TimeframeSpecV2("5m", "5min"),
    TimeframeSpecV2("15m", "15min"),
    TimeframeSpecV2("30m", "30min"),
    TimeframeSpecV2("1h", "1h"),
    TimeframeSpecV2("4h", "4h"),
)


def normalize_canonical_1m_v2(points: Iterable[tuple[str, float]]) -> pd.DataFrame:
    rows = [(stamp, float(price)) for stamp, price in points]
    if not rows:
        raise ValueError("Technical Core v2 requires canonical 1m history")

    frame = pd.DataFrame(rows, columns=["timestamp", "close"])
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.dropna(subset=["timestamp", "close"]).sort_values("timestamp")
    frame = frame.drop_duplicates("timestamp", keep="last")
    if frame.empty:
        raise ValueError("Canonical 1m history contained no valid observations")

    # v2 currently persists canonical minute observations as prices rather than
    # provider OHLC payloads. Preserve that contract explicitly: each observed
    # minute is a one-price bar and higher timeframes aggregate those observations.
    for column in ("open", "high", "low"):
        frame[column] = frame["close"]
    return frame.reset_index(drop=True)


def resample_live_timeframe_v2(frame: pd.DataFrame, rule: str) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()

    data = frame.set_index("timestamp")
    latest_observation = frame["timestamp"].iloc[-1]
    aggregated = data.resample(
        rule,
        label="left",
        closed="left",
        origin="epoch",
    ).agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
    )
    aggregated = aggregated.dropna(subset=["close"])
    if aggregated.empty:
        return aggregated.reset_index()

    # Live Technical Core deliberately includes the currently forming bucket.
    # Missing canonical minutes are not forward-filled: a gap is absence of
    # evidence, not a synthetic flat market. The active bucket's close is the
    # latest real observation available inside that bucket.
    aggregated = aggregated.loc[aggregated.index <= latest_observation]
    return aggregated.reset_index()


def build_runtime_frames_from_canonical_1m_v2(
    points: Iterable[tuple[str, float]],
    *,
    timeframes: Mapping[str, str] | None = None,
) -> dict[str, pd.DataFrame]:
    one_minute = normalize_canonical_1m_v2(points)
    rules = dict(timeframes) if timeframes is not None else {
        spec.name: spec.rule for spec in DEFAULT_TIMEFRAME_SPECS_V2
    }
    frames: dict[str, pd.DataFrame] = {"1m": one_minute}
    for name, rule in rules.items():
        frames[name] = resample_live_timeframe_v2(one_minute, rule)
    return frames
