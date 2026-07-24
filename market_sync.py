from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping

import pandas as pd


_INTERVAL_MINUTES = {
    "1min": 1,
    "5min": 5,
    "15min": 15,
    "30min": 30,
    "1h": 60,
    "5m": 5,
    "30m": 30,
}


@dataclass(frozen=True, slots=True)
class SynchronizedMarketSnapshot:
    frames: dict[str, pd.DataFrame]
    cutoff: pd.Timestamp
    received_at: pd.Timestamp
    lag_minutes: float
    source_end_times: dict[str, pd.Timestamp]
    mode: str = "SYNCHRONIZED_SIM"


def _interval_minutes(label: str) -> int:
    try:
        return _INTERVAL_MINUTES[label]
    except KeyError as exc:
        raise ValueError(f"Ukjent tidsramme for synkronisering: {label}") from exc


def _completed_bar_end(frame: pd.DataFrame, timeframe: str) -> pd.Series:
    if "timestamp" not in frame.columns:
        raise ValueError(f"{timeframe} mangler timestamp-kolonne")
    timestamps = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    return timestamps + pd.to_timedelta(_interval_minutes(timeframe), unit="m")


def synchronize_market_frames(
    frames: Mapping[str, pd.DataFrame],
    *,
    received_at: datetime | pd.Timestamp | None = None,
) -> SynchronizedMarketSnapshot:
    """Cut every required timeframe to the latest completed bar shared by all streams."""

    if not frames:
        raise ValueError("Ingen markedsrammer å synkronisere")

    source_end_times: dict[str, pd.Timestamp] = {}
    prepared: dict[str, pd.DataFrame] = {}

    for timeframe, source in frames.items():
        if source is None or source.empty:
            raise ValueError(f"{timeframe} har ingen markedsdata")
        frame = source.copy()
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
        frame = frame.dropna(subset=["timestamp", "close"]).sort_values("timestamp").reset_index(drop=True)
        if frame.empty:
            raise ValueError(f"{timeframe} har ingen gyldige prisbarer")
        frame["_bar_end"] = _completed_bar_end(frame, timeframe)
        source_end_times[timeframe] = pd.Timestamp(frame["_bar_end"].iloc[-1])
        prepared[timeframe] = frame

    cutoff = min(source_end_times.values())
    synchronized: dict[str, pd.DataFrame] = {}
    for timeframe, frame in prepared.items():
        trimmed = frame[frame["_bar_end"] <= cutoff].drop(columns=["_bar_end"]).reset_index(drop=True)
        if trimmed.empty:
            raise ValueError(f"{timeframe} har ingen ferdige barer ved felles cutoff {cutoff.isoformat()}")
        synchronized[timeframe] = trimmed

    received = pd.Timestamp(received_at or datetime.now(timezone.utc))
    if received.tzinfo is None:
        received = received.tz_localize("UTC")
    else:
        received = received.tz_convert("UTC")
    lag_minutes = max((received - cutoff).total_seconds() / 60.0, 0.0)

    return SynchronizedMarketSnapshot(
        frames=synchronized,
        cutoff=cutoff,
        received_at=received,
        lag_minutes=lag_minutes,
        source_end_times=source_end_times,
    )
