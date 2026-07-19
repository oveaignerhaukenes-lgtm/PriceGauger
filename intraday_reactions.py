from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

import pandas as pd
import yfinance as yf

from event_models import MarketEvent

INTERVALS = ("5m", "15m", "60m")
WINDOWS_MINUTES = {
    "return_5m_pct": 5,
    "return_15m_pct": 15,
    "return_30m_pct": 30,
    "return_1h_pct": 60,
    "return_4h_pct": 240,
    "return_24h_pct": 1440,
}


@dataclass(slots=True)
class IntradayReaction:
    event_id: str
    asset: str
    symbol: str
    published_at: str
    interval: str
    anchor_time: str
    anchor_lag_minutes: float
    base_price: float
    return_5m_pct: float | None
    return_15m_pct: float | None
    return_30m_pct: float | None
    return_1h_pct: float | None
    return_4h_pct: float | None
    return_24h_pct: float | None
    max_up_24h_pct: float | None
    max_down_24h_pct: float | None
    time_to_max_minutes: float | None
    time_to_min_minutes: float | None

    def to_record(self) -> dict:
        return asdict(self)


def _empty_prices() -> pd.DataFrame:
    return pd.DataFrame(columns=["time", "open", "close", "high", "low"])


def fetch_intraday_prices(
    symbol: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    interval: str,
) -> pd.DataFrame:
    frame = yf.download(
        symbol,
        start=start.date().isoformat(),
        end=(end + pd.Timedelta(days=1)).date().isoformat(),
        interval=interval,
        auto_adjust=False,
        progress=False,
        threads=False,
        prepost=False,
    )
    if frame.empty:
        return _empty_prices()
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    frame = frame.reset_index()
    time_col = "Datetime" if "Datetime" in frame.columns else frame.columns[0]
    frame = frame.rename(
        columns={
            time_col: "time",
            "Open": "open",
            "Close": "close",
            "High": "high",
            "Low": "low",
        }
    )
    frame["time"] = pd.to_datetime(frame["time"], utc=True, errors="coerce")
    for column in ("open", "close", "high", "low"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return (
        frame.dropna(subset=["time", "open", "close"])
        .sort_values("time")
        .reset_index(drop=True)
    )


def _pct(value: float | None, base: float) -> float | None:
    if value is None or pd.isna(value) or base == 0:
        return None
    return (float(value) / base - 1.0) * 100.0


def _close_at_or_after(prices: pd.DataFrame, target: pd.Timestamp) -> float | None:
    rows = prices[prices["time"] >= target]
    if rows.empty:
        return None
    return float(rows.iloc[0]["close"])


def _best_interval_cache(
    assets: dict[str, str],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> dict[str, tuple[str, pd.DataFrame]]:
    cache: dict[str, tuple[str, pd.DataFrame]] = {}
    for asset, symbol in assets.items():
        selected = ("", _empty_prices())
        for interval in INTERVALS:
            prices = fetch_intraday_prices(symbol, start, end, interval)
            if not prices.empty:
                selected = (interval, prices)
                break
        cache[asset] = selected
    return cache


def calculate_intraday_reactions(
    events: Iterable[MarketEvent],
    assets: dict[str, str],
) -> list[IntradayReaction]:
    rows = [event for event in events if getattr(event, "published_at", None)]
    timestamps = [
        pd.to_datetime(event.published_at, utc=True, errors="coerce") for event in rows
    ]
    valid = [timestamp for timestamp in timestamps if not pd.isna(timestamp)]
    if not valid:
        return []

    start = min(valid) - pd.Timedelta(days=1)
    end = max(valid) + pd.Timedelta(days=2)
    cache = _best_interval_cache(assets, start, end)
    reactions: list[IntradayReaction] = []

    for event in rows:
        published = pd.to_datetime(event.published_at, utc=True, errors="coerce")
        if pd.isna(published):
            continue

        for asset, symbol in assets.items():
            interval, prices = cache[asset]
            if prices.empty:
                continue
            future = prices[prices["time"] >= published].reset_index(drop=True)
            if future.empty:
                continue

            anchor = future.iloc[0]
            anchor_time = pd.Timestamp(anchor["time"])
            base_price = float(anchor["open"])
            lag = (anchor_time - published).total_seconds() / 60.0

            returns = {
                name: _pct(
                    _close_at_or_after(prices, published + pd.Timedelta(minutes=minutes)),
                    base_price,
                )
                for name, minutes in WINDOWS_MINUTES.items()
            }

            window = prices[
                (prices["time"] >= anchor_time)
                & (prices["time"] <= published + pd.Timedelta(hours=24))
            ]
            if window.empty:
                max_up = max_down = None
                time_to_max = time_to_min = None
            else:
                max_row = window.loc[window["high"].idxmax()]
                min_row = window.loc[window["low"].idxmin()]
                max_up = _pct(float(max_row["high"]), base_price)
                max_down = _pct(float(min_row["low"]), base_price)
                time_to_max = (
                    pd.Timestamp(max_row["time"]) - published
                ).total_seconds() / 60.0
                time_to_min = (
                    pd.Timestamp(min_row["time"]) - published
                ).total_seconds() / 60.0

            reactions.append(
                IntradayReaction(
                    event_id=event.event_id,
                    asset=asset,
                    symbol=symbol,
                    published_at=published.isoformat().replace("+00:00", "Z"),
                    interval=interval,
                    anchor_time=anchor_time.isoformat().replace("+00:00", "Z"),
                    anchor_lag_minutes=lag,
                    base_price=base_price,
                    max_up_24h_pct=max_up,
                    max_down_24h_pct=max_down,
                    time_to_max_minutes=time_to_max,
                    time_to_min_minutes=time_to_min,
                    **returns,
                )
            )

    return reactions
