"""Separate TECH and MACRO news research channels; zero external/API calls.

Headline topic detection is only for routing to a reader. It MUST NOT infer
directional market impact from a keyword. Direction requires a separately
assessed and out-of-sample validated signed impact, with source timestamps.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Sequence

from tech100_four_channel_synthesis_v1 import ChannelSignal, MACRO_NEWS, TECH_NEWS

TECH_WORDS = (
    "nvidia", "microsoft", "apple", "alphabet", "google", "meta", "amazon",
    "semiconductor", "chipmaker", "nasdaq", "datacenter", "data center",
    "artificial intelligence", "ai spending", "cloud revenue", "earnings guidance",
)
MACRO_WORDS = (
    "federal reserve", "fed rate", "cpi", "ppi", "inflation", "nfp",
    "nonfarm payroll", "jobs report", "treasury yield", "gdp", "recession",
    "interest rate", "unemployment", "oil supply", "tariff", "trade war",
)


def classify_news_topic(headline: str) -> tuple[str, ...]:
    """Route headline to possible topical readers, without creating a trade."""
    haystack = " ".join(str(headline).lower().split())
    topics = []
    if any(word in haystack for word in TECH_WORDS):
        topics.append(TECH_NEWS)
    if any(word in haystack for word in MACRO_WORDS):
        topics.append(MACRO_NEWS)
    return tuple(topics)


def _utc(at: datetime) -> datetime:
    if at.tzinfo is None:
        raise ValueError("news timestamps must be timezone-aware")
    return at.astimezone(timezone.utc)


@dataclass(frozen=True)
class AssessedNewsItem:
    story_id: str
    channel: str
    source: str
    published_at: datetime
    received_at: datetime
    horizon_minutes: int
    expected_tech100_return_pct: float | None
    confidence: float
    out_of_sample_validated: bool = False

    def __post_init__(self) -> None:
        if self.channel not in (TECH_NEWS, MACRO_NEWS):
            raise ValueError("invalid news channel")
        if not self.story_id or not self.source or self.horizon_minutes <= 0:
            raise ValueError("news needs identity, source and forecast horizon")
        if _utc(self.received_at) < _utc(self.published_at):
            raise ValueError("received before publication")
        if not isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("invalid news confidence")
        if self.expected_tech100_return_pct is not None and not isfinite(self.expected_tech100_return_pct):
            raise ValueError("invalid news forecast")


def news_channel_signal(
    *, channel: str, at: datetime, horizon_minutes: int,
    news: Sequence[AssessedNewsItem], max_age: timedelta = timedelta(minutes=30),
) -> ChannelSignal:
    """As-of aggregate; unsupported headlines cannot act as bullish/bearish votes."""
    if channel not in (TECH_NEWS, MACRO_NEWS) or horizon_minutes <= 0 or max_age < timedelta(0):
        raise ValueError("invalid channel/horizon/age")
    at = _utc(at)
    seen: set[str] = set()
    accepted: list[AssessedNewsItem] = []
    for item in news:
        if item.channel != channel or item.horizon_minutes != horizon_minutes:
            continue
        # Do not read news that was published before but arrived after decision.
        age = at - _utc(item.received_at)
        if not timedelta(0) <= age <= max_age:
            continue
        if item.story_id in seen:
            continue
        seen.add(item.story_id)
        if (item.expected_tech100_return_pct is None or not item.out_of_sample_validated
                or item.confidence <= 0):
            continue
        accepted.append(item)
    if not accepted:
        return ChannelSignal(channel, at, horizon_minutes, None, 0.0,
                             ("No validated directional news assessments",), False)
    weights = [item.confidence for item in accepted]
    weighted_forecast = sum(item.expected_tech100_return_pct * weight
                            for item, weight in zip(accepted, weights)) / sum(weights)
    return ChannelSignal(channel, at, horizon_minutes, weighted_forecast,
                         min(1.0, sum(weights) / len(weights)),
                         tuple(f"{item.source}:{item.story_id}" for item in accepted), True)
