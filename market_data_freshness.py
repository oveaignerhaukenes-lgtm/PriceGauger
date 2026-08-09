from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from realtime_market_data import RealtimeBar1m, StreamStatus, utc


@dataclass(frozen=True, slots=True)
class MarketDataFreshness:
    state: str
    label: str
    detail: str
    bar_age_seconds: float | None
    quote_age_seconds: float | None


def _age(value: str | None, *, now: datetime) -> float | None:
    if not value:
        return None
    try:
        stamp = utc(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, (now - stamp).total_seconds())


def _duration(seconds: float | None) -> str:
    if seconds is None:
        return "ukjent"
    if seconds < 90:
        return f"{int(seconds)} s"
    minutes = seconds / 60.0
    if minutes < 90:
        return f"{minutes:.0f} min"
    return f"{minutes / 60.0:.1f} t"


def classify_market_data_freshness(
    *,
    bar: RealtimeBar1m | None,
    status: StreamStatus | None,
    now: datetime | None = None,
    expected_bar_seconds: float = 180.0,
    recent_quote_seconds: float = 120.0,
) -> MarketDataFreshness:
    """Classify data health without treating a quiet/closed market as a stream failure.

    A stale bar is considered a definite pipeline warning only when quotes are still
    arriving recently. If both quote and bar are old, the UI reports quiet/stale data
    neutrally because the market may simply be closed.
    """

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)

    bar_age = _age(None if bar is None else bar.bar_time, now=current)
    quote_age = _age(None if status is None else status.last_quote_at, now=current)
    stream_state = "UNKNOWN" if status is None else str(status.state or "UNKNOWN").upper()

    if status is not None and stream_state not in {"CONNECTED", "ACTIVE", "STREAMING", "SUBSCRIBED"}:
        return MarketDataFreshness(
            state="STREAM_WARNING",
            label=f"Stream {stream_state}",
            detail=f"siste quote {_duration(quote_age)} siden · siste 1m-bar {_duration(bar_age)} siden",
            bar_age_seconds=bar_age,
            quote_age_seconds=quote_age,
        )

    if bar is None:
        return MarketDataFreshness(
            state="NO_BARS",
            label="Ingen canonical bars",
            detail=f"siste quote {_duration(quote_age)} siden",
            bar_age_seconds=None,
            quote_age_seconds=quote_age,
        )

    if quote_age is not None and quote_age <= recent_quote_seconds and bar_age is not None and bar_age > expected_bar_seconds:
        return MarketDataFreshness(
            state="BAR_PIPELINE_WARNING",
            label="Quotes kommer, men 1m-bars henger",
            detail=f"siste quote {_duration(quote_age)} siden · siste 1m-bar {_duration(bar_age)} siden",
            bar_age_seconds=bar_age,
            quote_age_seconds=quote_age,
        )

    if bar_age is not None and bar_age <= expected_bar_seconds:
        return MarketDataFreshness(
            state="FRESH",
            label="Canonical data flyter",
            detail=f"siste 1m-bar {_duration(bar_age)} siden · siste quote {_duration(quote_age)} siden",
            bar_age_seconds=bar_age,
            quote_age_seconds=quote_age,
        )

    return MarketDataFreshness(
        state="QUIET_OR_STALE",
        label="Ingen fersk bar",
        detail=f"siste 1m-bar {_duration(bar_age)} siden · siste quote {_duration(quote_age)} siden; markedet kan være stille/stengt",
        bar_age_seconds=bar_age,
        quote_age_seconds=quote_age,
    )
