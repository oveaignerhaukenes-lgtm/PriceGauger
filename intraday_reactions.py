from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Iterable

import pandas as pd
import yfinance as yf

from event_models import MarketEvent

INTERVALS = ("5m", "15m", "60m")
INTERVAL_MINUTES = {"5m": 5, "15m": 15, "60m": 60}
WINDOWS_MINUTES = {
    "return_5m_pct": 5,
    "return_15m_pct": 15,
    "return_30m_pct": 30,
    "return_1h_pct": 60,
    "return_4h_pct": 240,
    "return_24h_pct": 1440,
}
WINDOW_TIME_FIELDS = {
    "return_5m_pct": "bar_time_5m",
    "return_15m_pct": "bar_time_15m",
    "return_30m_pct": "bar_time_30m",
    "return_1h_pct": "bar_time_1h",
    "return_4h_pct": "bar_time_4h",
    "return_24h_pct": "bar_time_24h",
}


@dataclass(slots=True)
class IntradayReaction:
    event_id: str
    event_title: str
    asset: str
    symbol: str
    published_at: str
    interval: str
    anchor_time: str
    anchor_lag_minutes: float
    market_state: str
    base_price: float
    return_5m_pct: float | None
    return_15m_pct: float | None
    return_30m_pct: float | None
    return_1h_pct: float | None
    return_4h_pct: float | None
    return_24h_pct: float | None
    bar_time_5m: str | None
    bar_time_15m: str | None
    bar_time_30m: str | None
    bar_time_1h: str | None
    bar_time_4h: str | None
    bar_time_24h: str | None
    distinct_window_bars: int
    duplicate_group_size: int
    quality_score: float
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
        .drop_duplicates(subset=["time"], keep="last")
        .sort_values("time")
        .reset_index(drop=True)
    )


def _pct(value: float | None, base: float) -> float | None:
    if value is None or pd.isna(value) or base == 0:
        return None
    return (float(value) / base - 1.0) * 100.0


def _bar_at_or_after(
    prices: pd.DataFrame, target: pd.Timestamp
) -> tuple[float | None, pd.Timestamp | None]:
    rows = prices[prices["time"] >= target]
    if rows.empty:
        return None, None
    row = rows.iloc[0]
    return float(row["close"]), pd.Timestamp(row["time"])


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


def _normalised_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def _event_dedup_key(event: MarketEvent) -> str:
    raw = event.raw if isinstance(event.raw, dict) else {}
    source_url = str(raw.get("_timestamp_article_url") or "").strip().lower()
    if source_url:
        return f"url:{source_url}"
    title = _normalised_title(str(getattr(event, "title", "")))
    published = str(getattr(event, "published_at", ""))[:16]
    return f"title:{title}|minute:{published}"


def _deduplicate_events(events: Iterable[MarketEvent]) -> list[tuple[MarketEvent, int]]:
    groups: dict[str, list[MarketEvent]] = {}
    for event in events:
        if not getattr(event, "published_at", None):
            continue
        groups.setdefault(_event_dedup_key(event), []).append(event)
    return [(group[0], len(group)) for group in groups.values()]


def _market_state(anchor_lag: float, interval: str) -> str:
    expected = INTERVAL_MINUTES.get(interval, 60)
    if anchor_lag <= expected + 1:
        return "open"
    if anchor_lag <= 120:
        return "short_gap"
    return "closed_or_data_gap"


def _quality_score(
    event: MarketEvent,
    interval: str,
    anchor_lag: float,
    distinct_bars: int,
    duplicate_group_size: int,
) -> float:
    score = 0.0
    timestamp_confidence = getattr(event, "timestamp_confidence", None)
    score += 35.0 * float(timestamp_confidence if timestamp_confidence is not None else 0.5)
    score += {"5m": 25.0, "15m": 17.0, "60m": 8.0}.get(interval, 0.0)
    if anchor_lag <= INTERVAL_MINUTES.get(interval, 60) + 1:
        score += 20.0
    elif anchor_lag <= 120:
        score += 10.0
    score += min(distinct_bars, len(WINDOWS_MINUTES)) / len(WINDOWS_MINUTES) * 15.0
    score += 5.0 if duplicate_group_size == 1 else max(0.0, 5.0 - duplicate_group_size)
    return round(min(score, 100.0), 1)


def _iso(value: pd.Timestamp | None) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


def calculate_intraday_reactions(
    events: Iterable[MarketEvent],
    assets: dict[str, str],
) -> list[IntradayReaction]:
    deduplicated = _deduplicate_events(events)
    valid_events: list[tuple[MarketEvent, int, pd.Timestamp]] = []
    for event, group_size in deduplicated:
        timestamp = pd.to_datetime(event.published_at, utc=True, errors="coerce")
        if not pd.isna(timestamp):
            valid_events.append((event, group_size, timestamp))
    if not valid_events:
        return []

    timestamps = [timestamp for _, _, timestamp in valid_events]
    start = min(timestamps) - pd.Timedelta(days=1)
    end = max(timestamps) + pd.Timedelta(days=2)
    cache = _best_interval_cache(assets, start, end)
    reactions: list[IntradayReaction] = []

    for event, duplicate_group_size, published in valid_events:
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
            lag = max(0.0, (anchor_time - published).total_seconds() / 60.0)

            returns: dict[str, float | None] = {}
            bar_times: dict[str, str | None] = {}
            used_times: set[pd.Timestamp] = set()
            for return_name, minutes in WINDOWS_MINUTES.items():
                # Reaction windows start when the market can first trade the news.
                target = anchor_time + pd.Timedelta(minutes=minutes)
                value, bar_time = _bar_at_or_after(prices, target)
                returns[return_name] = _pct(value, base_price)
                bar_times[WINDOW_TIME_FIELDS[return_name]] = _iso(bar_time)
                if bar_time is not None:
                    used_times.add(bar_time)

            distinct_bars = len(used_times)
            state = _market_state(lag, interval)
            quality = _quality_score(
                event, interval, lag, distinct_bars, duplicate_group_size
            )

            window_end = anchor_time + pd.Timedelta(hours=24)
            window = prices[
                (prices["time"] >= anchor_time) & (prices["time"] <= window_end)
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
                    pd.Timestamp(max_row["time"]) - anchor_time
                ).total_seconds() / 60.0
                time_to_min = (
                    pd.Timestamp(min_row["time"]) - anchor_time
                ).total_seconds() / 60.0

            reactions.append(
                IntradayReaction(
                    event_id=event.event_id,
                    event_title=str(getattr(event, "title", "")),
                    asset=asset,
                    symbol=symbol,
                    published_at=published.isoformat().replace("+00:00", "Z"),
                    interval=interval,
                    anchor_time=anchor_time.isoformat().replace("+00:00", "Z"),
                    anchor_lag_minutes=lag,
                    market_state=state,
                    base_price=base_price,
                    distinct_window_bars=distinct_bars,
                    duplicate_group_size=duplicate_group_size,
                    quality_score=quality,
                    max_up_24h_pct=max_up,
                    max_down_24h_pct=max_down,
                    time_to_max_minutes=time_to_max,
                    time_to_min_minutes=time_to_min,
                    **returns,
                    **bar_times,
                )
            )
    return reactions
