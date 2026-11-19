"""Read-only adapters to PriceGauger's existing canonical Saxo and news data.

No Saxo REST/stream call, OAuth refresh, AI call, DB write, order or trade.
Data is always matched by exact subscribed provider instrument identity. A
missing/delayed yield feed remains missing; Treasury futures are not yields.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from typing import Mapping, Sequence

from canonical_market_bars_v2 import (
    CanonicalMarketBarStoreV2, CanonicalMarketBarV2, QUALITY_REALTIME,
)
from cross_market_state import CrossMarketStateSnapshot
from database import connect
from instrument_registry_v2 import InstrumentSourceV2, list_subscribed_sources_v2
from tech100_news_channels_v1 import classify_news_topic

PRICE_CHANNELS = ("Tech100", "Gold", "Brent", "DXY")
YIELD_CHANNELS = ("US2Y", "US10Y", "US30Y")
TECH100_EXACT_UIC = "4912"


def _utc(value: str | datetime, *, database_utc: bool = False) -> datetime:
    at = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if at.tzinfo is None:
        if not database_utc:
            raise ValueError("source timestamps must have a timezone")
        # Database CURRENT_TIMESTAMP is stored in UTC (possibly without tz).
        at = at.replace(tzinfo=timezone.utc)
    return at.astimezone(timezone.utc)


def _market_group(source: InstrumentSourceV2) -> str | None:
    market = source.market_name.casefold()
    if source.provider.casefold() != "saxo":
        return None
    if (source.provider_instrument_id == TECH100_EXACT_UIC
            and ("tech 100" in market or "tech100" in market or "nas100" in market)):
        return "Tech100"
    if "gold" in market:
        return "Gold"
    if "brent" in market:
        return "Brent"
    if (market == "dxy" or "dollar index" in market or "usdx" in market):
        return "DXY"
    return None


def source_candidates(
    sources: Sequence[InstrumentSourceV2],
) -> dict[str, tuple[InstrumentSourceV2, ...]]:
    """Expose subscribed candidate identities for a manual source picker."""
    return {
        channel: tuple(item for item in sources if _market_group(item) == channel)
        for channel in PRICE_CHANNELS
    }


def resolve_exact_subscriptions(
    sources: Sequence[InstrumentSourceV2],
    *, selected_uics: Mapping[str, str] | None = None,
) -> dict[str, InstrumentSourceV2]:
    """Demand one unambiguous subscribed Saxo instrument for each price series."""
    choices = dict(selected_uics or {})
    if any(name not in PRICE_CHANNELS for name in choices):
        raise ValueError("unknown market selection")
    selected = {}
    for name in PRICE_CHANNELS:
        candidates = [source for source in sources if _market_group(source) == name]
        uic = choices.get(name)
        if uic is not None:
            candidates = [item for item in candidates if item.provider_instrument_id == uic]
        if len(candidates) != 1:
            raise LookupError(f"{name} requires one exact subscribed Saxo UIC; got {len(candidates)}")
        selected[name] = candidates[0]
    return selected


@dataclass(frozen=True)
class PriceSourceWindow:
    source: InstrumentSourceV2
    bars: tuple[CanonicalMarketBarV2, ...]


def load_canonical_prices(
    *,
    at: datetime,
    lookback_minutes: int,
    path: str | Path = "pricegauger.db",
    selected_uics: Mapping[str, str] | None = None,
    subscriptions: Sequence[InstrumentSourceV2] | None = None,
) -> dict[str, PriceSourceWindow]:
    """Existing canonical store only; filter incomplete/current/backfilled bars."""
    at = _utc(at)
    if not 1 <= lookback_minutes <= 1440:
        raise ValueError("lookback must be 1..1440 minutes")
    sources = resolve_exact_subscriptions(
        subscriptions if subscriptions is not None else list_subscribed_sources_v2(provider="saxo"),
        selected_uics=selected_uics,
    )
    # Bar_time denotes 1m bucket START, not its completion. A 12:00 bar must
    # not inform a 12:00:15 strategy decision.
    latest_start = at.replace(second=0, microsecond=0) - timedelta(minutes=1)
    start = latest_start - timedelta(minutes=lookback_minutes)
    store = CanonicalMarketBarStoreV2(path)
    out: dict[str, PriceSourceWindow] = {}
    for name, source in sources.items():
        raw = store.load_instrument_range(
            instrument_id=source.instrument_id,
            start=start, end=latest_start,
            limit=lookback_minutes + 1,
        )
        valid = tuple(
            bar for bar in raw
            if bar.instrument_id == source.instrument_id
            and (_utc(bar.bar_time) + timedelta(minutes=1)) <= at
            and (bar.quality_flags & QUALITY_REALTIME) == QUALITY_REALTIME
            and bar.close > 0
        )
        out[name] = PriceSourceWindow(source, valid)
    return out


@dataclass(frozen=True)
class PriceMoveSnapshot:
    at: datetime
    lookback_minutes: int
    latest_complete_bar_start: datetime
    returns_pct: Mapping[str, float]
    status: str
    reason: str
    source_ids: Mapping[str, str]


def aligned_price_moves(
    windows: Mapping[str, PriceSourceWindow],
    *, at: datetime, lookback_minutes: int,
) -> PriceMoveSnapshot:
    """No forward-filling, cross-UIC joins, incomplete bars or gap bridging."""
    at = _utc(at)
    latest = at.replace(second=0, microsecond=0) - timedelta(minutes=1)
    if set(windows) != set(PRICE_CHANNELS) or lookback_minutes <= 0:
        raise ValueError("expected Tech100, Gold, Brent and DXY windows and positive lookback")
    result: dict[str, float] = {}
    ids = {name: item.source.provider_instrument_id for name, item in windows.items()}
    for name in PRICE_CHANNELS:
        window = windows[name]
        bars = window.bars
        required = [latest - timedelta(minutes=lookback_minutes - index)
                    for index in range(lookback_minutes + 1)]
        times = [_utc(bar.bar_time) for bar in bars]
        if times != required:
            return PriceMoveSnapshot(at, lookback_minutes, latest, {}, "INCOMPLETE",
                                     f"{name}: missing/stale/non-contiguous 1m source", ids)
        if any((bar.quality_flags & QUALITY_REALTIME) != QUALITY_REALTIME or bar.close <= 0
               for bar in bars):
            return PriceMoveSnapshot(at, lookback_minutes, latest, {}, "INCOMPLETE",
                                     f"{name}: invalid/backfilled source", ids)
        result[name] = (bars[-1].close / bars[0].close - 1.0) * 100.0
    return PriceMoveSnapshot(at, lookback_minutes, latest, result, "VALID", "exact canonical real-time 1m series", ids)


@dataclass(frozen=True)
class YieldFeedStatus:
    tenor: str
    status: str
    provider: str
    detail: str


def yield_feed_status(
    snapshot: CrossMarketStateSnapshot | None, *, at: datetime,
) -> tuple[YieldFeedStatus, ...]:
    """Audit existing CrossMarket yields without fabricating 1m yield ticks."""
    at = _utc(at)
    observations = {item.name: item for item in snapshot.observations} if snapshot else {}
    result = []
    for tenor in YIELD_CHANNELS:
        item = observations.get(tenor)
        if item is None or item.provider == "unconfigured" or item.value is None:
            result.append(YieldFeedStatus(tenor, "MISSING", "unconfigured", "no verified US Treasury yield observation"))
            continue
        age = at - _utc(item.observed_at) if item.observed_at else timedelta.max
        if not timedelta(0) <= age <= timedelta(minutes=5):
            result.append(YieldFeedStatus(tenor, "STALE", item.provider, "yield timestamp too old/future"))
        elif item.latest_observation_freshness != "FRESH":
            result.append(YieldFeedStatus(tenor, "UNVERIFIED", item.provider, "source not marked fresh"))
        elif item.window_coverage.get("15m") != "VALID":
            result.append(YieldFeedStatus(tenor, "NO_15M_REFERENCE", item.provider, "historical yield change unavailable"))
        else:
            # CrossMarket only supports 15m/1h/4h changes; 1m impulse signals
            # still need separate sourced timestamped yield changes.
            result.append(YieldFeedStatus(tenor, "15M_ONLY", item.provider, "no verified 1m yield impulse series"))
    return tuple(result)


def load_archived_yield_snapshot(
    *, at: datetime, path: str | Path = "pricegauger.db",
) -> CrossMarketStateSnapshot | None:
    """Read an existing as-of state, without CrossMarketStateStore schema writes."""
    at = _utc(at)
    with connect(path) as db:
        try:
            row = db.execute(
                """SELECT payload_json FROM cross_market_state_snapshots
                   WHERE as_of <= ? ORDER BY as_of DESC LIMIT 1""",
                (at.isoformat(),),
            ).fetchone()
        except Exception as exc:
            # No schema setup or implicit data provider for a research reader.
            raise LookupError("no existing cross-market snapshot archive") from exc
    if row is None:
        return None
    payload = row["payload_json"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    snapshot = CrossMarketStateSnapshot.from_record(payload)
    if _utc(snapshot.as_of) > at:
        raise ValueError("future cross-market snapshot")
    return snapshot


@dataclass(frozen=True)
class ArchivedNewsHeadline:
    story_id: str
    source: str
    headline: str
    published_at: datetime
    received_at: datetime
    topics: tuple[str, ...]


def _archive_news_row(row: Mapping[str, object], *, at: datetime, within: timedelta) -> ArchivedNewsHeadline | None:
    """Only existing Telegram raw archive text; no speculative sentiment."""
    payload = row["payload_json"]
    record = json.loads(payload) if isinstance(payload, str) else dict(payload or {})
    content = str(record.get("message_text") or "").strip()
    if not content:
        return None
    published = _utc(str(row["published_at"]))
    received = _utc(str(row["first_seen_at"]), database_utc=True)
    if not (published <= received <= at and timedelta(0) <= at - received <= within):
        return None
    # Limit stored/displayed headline for bounded on-page research, not for
    # underlying source ingestion or any costly NLP step.
    summary = " ".join(content.split())[:500]
    topics = classify_news_topic(summary)
    if not topics:
        return None
    return ArchivedNewsHeadline(str(row["message_id"]), str(row["channel"]),
                                summary, published, received, topics)


def load_archived_news(
    *, at: datetime, within: timedelta = timedelta(hours=4),
    path: str | Path = "pricegauger.db", limit: int = 250,
) -> tuple[ArchivedNewsHeadline, ...]:
    """Read bounded archived headlines; no fetching/reclassification with AI.

    This archive contains source candidates, NOT scored market-direction impact.
    A news entry remains unavailable to synthesis until a separate validated
    signed-impact estimator has been trained and explicitly enabled.
    """
    at = _utc(at)
    if within < timedelta(0) or not 1 <= limit <= 1000:
        raise ValueError("bounded read required")
    with connect(path) as db:
        rows = db.execute(
            """SELECT message_id, channel, published_at, first_seen_at, payload_json
               FROM telegram_raw_posts ORDER BY first_seen_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    matched: list[ArchivedNewsHeadline] = []
    for row in rows:
        try:
            entry = _archive_news_row(row, at=at, within=within)
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            continue  # malformed source is not a valid market signal
        if entry is not None:
            matched.append(entry)
    return tuple(sorted(matched, key=lambda item: (item.received_at, item.story_id)))


def load_archived_gdelt_news(
    *, at: datetime, database_path: str | Path,
    within: timedelta = timedelta(hours=4), limit: int = 250,
) -> tuple[ArchivedNewsHeadline, ...]:
    """Read already-stored legacy GDELT candidates (separate local SQLite).

    Opens the archive *read-only*; never creates a missing file/table or queries
    GDELT externally. Production may not have this legacy SQLite archive at all.
    """
    at = _utc(at)
    path = Path(database_path)
    if within < timedelta(0) or not 1 <= limit <= 1000:
        raise ValueError("bounded read required")
    if not path.is_file():
        raise FileNotFoundError(f"GDELT archive not present: {path.name}")
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                """SELECT event_id, provider, title, published_at, retrieved_at
                   FROM gdelt_candidates ORDER BY retrieved_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            raise LookupError("GDELT archive has no candidate table") from exc
    found: list[ArchivedNewsHeadline] = []
    for row in rows:
        try:
            published, received = _utc(row["published_at"]), _utc(row["retrieved_at"])
        except (TypeError, ValueError):
            continue
        if not (published <= received <= at and timedelta(0) <= at - received <= within):
            continue
        title = " ".join(str(row["title"] or "").split())[:500]
        topics = classify_news_topic(title)
        if not topics:
            continue
        found.append(ArchivedNewsHeadline(
            f"gdelt:{row['provider']}:{row['event_id']}", f"gdelt:{row['provider']}",
            title, published, received, topics,
        ))
    return tuple(sorted(found, key=lambda item: (item.received_at, item.story_id)))
