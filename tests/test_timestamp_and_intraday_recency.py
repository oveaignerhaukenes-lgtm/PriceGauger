from __future__ import annotations

import pandas as pd

from event_models import MarketEvent
from intraday_reactions import _allowed_intervals, calculate_intraday_reactions
from timestamp_enrichment import enrich_event_timestamp


def _event(*, event_date: str, published_at: str | None = None, raw: dict | None = None) -> MarketEvent:
    return MarketEvent(
        event_id="event-1",
        source="test",
        event_date=event_date,
        title="Test event",
        summary="",
        category="",
        subcategory="",
        domain="",
        country="",
        location="",
        actors=[],
        confidence=0.9,
        market_sensitivity=0.8,
        significance=0.8,
        url="",
        raw=raw or {},
        published_at=published_at,
        timestamp_source=None,
        timestamp_confidence=None,
    )


def test_enrichment_rejects_timestamp_far_from_event_date() -> None:
    today = pd.Timestamp.now(tz="UTC").normalize()
    event = _event(
        event_date=today.date().isoformat(),
        raw={"published_at": "2018-03-09T12:00:00Z"},
    )

    enriched = enrich_event_timestamp(event)

    assert enriched.published_at is None
    assert "irrelevant:gdelt:published_at" in enriched.raw["_timestamp_diagnostic"]


def test_interval_selection_respects_yahoo_history_windows() -> None:
    now = pd.Timestamp.now(tz="UTC")

    assert _allowed_intervals(now - pd.Timedelta(days=20)) == ("5m", "15m", "60m")
    assert _allowed_intervals(now - pd.Timedelta(days=90)) == ("60m",)
    assert _allowed_intervals(now - pd.Timedelta(days=800)) == ()


def test_intraday_reactions_ignore_events_older_than_two_years(monkeypatch) -> None:
    old = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=800)
    event = _event(
        event_date=old.date().isoformat(),
        published_at=old.isoformat(),
    )

    def unexpected_download(*args, **kwargs):
        raise AssertionError("Yahoo should not be called for stale events")

    monkeypatch.setattr("intraday_reactions.yf.download", unexpected_download)

    assert calculate_intraday_reactions([event], {"Brent": "BZ=F"}) == []
