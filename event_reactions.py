from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timedelta
from typing import Iterable

import pandas as pd
import yfinance as yf

from event_models import MarketEvent


@dataclass(slots=True)
class EventReaction:
    event_id: str
    asset: str
    symbol: str
    event_date: str
    base_date: str
    base_close: float
    return_1d_pct: float | None
    return_3d_pct: float | None
    return_5d_pct: float | None
    max_up_5d_pct: float | None
    max_down_5d_pct: float | None

    def to_record(self) -> dict:
        return asdict(self)


def fetch_daily_prices(symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    frame = yf.download(
        symbol,
        start=start.date().isoformat(),
        end=(end + timedelta(days=1)).date().isoformat(),
        interval="1d",
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    if frame.empty:
        return pd.DataFrame(columns=["date", "close", "high", "low"])
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    frame = frame.reset_index()
    date_col = "Date" if "Date" in frame.columns else frame.columns[0]
    frame = frame.rename(columns={date_col: "date", "Close": "close", "High": "high", "Low": "low"})
    frame["date"] = pd.to_datetime(frame["date"], utc=True, errors="coerce").dt.normalize()
    for column in ("close", "high", "low"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)


def _pct(value: float | None, base: float) -> float | None:
    if value is None or pd.isna(value) or base == 0:
        return None
    return (float(value) / base - 1.0) * 100.0


def calculate_reactions(
    events: Iterable[MarketEvent],
    assets: dict[str, str],
) -> list[EventReaction]:
    rows = list(events)
    valid_dates = [pd.to_datetime(event.event_date, utc=True, errors="coerce") for event in rows]
    valid_dates = [value.normalize() for value in valid_dates if not pd.isna(value)]
    if not valid_dates:
        return []

    start = min(valid_dates) - pd.Timedelta(days=7)
    end = max(valid_dates) + pd.Timedelta(days=14)
    price_cache = {asset: fetch_daily_prices(symbol, start, end) for asset, symbol in assets.items()}
    reactions: list[EventReaction] = []

    for event in rows:
        event_date = pd.to_datetime(event.event_date, utc=True, errors="coerce")
        if pd.isna(event_date):
            continue
        event_date = event_date.normalize()

        for asset, symbol in assets.items():
            prices = price_cache[asset]
            future = prices[prices["date"] >= event_date].reset_index(drop=True)
            if future.empty:
                continue
            base = future.iloc[0]
            base_close = float(base["close"])

            def close_at(offset: int) -> float | None:
                return float(future.iloc[offset]["close"]) if len(future) > offset else None

            window = future.iloc[:6]
            reactions.append(
                EventReaction(
                    event_id=event.event_id,
                    asset=asset,
                    symbol=symbol,
                    event_date=event_date.date().isoformat(),
                    base_date=base["date"].date().isoformat(),
                    base_close=base_close,
                    return_1d_pct=_pct(close_at(1), base_close),
                    return_3d_pct=_pct(close_at(3), base_close),
                    return_5d_pct=_pct(close_at(5), base_close),
                    max_up_5d_pct=_pct(window["high"].max() if not window.empty else None, base_close),
                    max_down_5d_pct=_pct(window["low"].min() if not window.empty else None, base_close),
                )
            )
    return reactions
