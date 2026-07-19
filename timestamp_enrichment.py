from __future__ import annotations

import json
from datetime import timezone
from typing import Any, Iterable

import pandas as pd
import requests
from bs4 import BeautifulSoup

from event_models import MarketEvent

USER_AGENT = "PriceGauger/0.7 (+timestamp enrichment)"
META_KEYS = (
    "article:published_time",
    "og:published_time",
    "datePublished",
    "datepublished",
    "publish-date",
    "pubdate",
    "publication_date",
    "date",
)
RAW_KEYS = (
    "published_at",
    "publication_time",
    "publication_datetime",
    "created_at",
    "datetime",
    "timestamp",
    "event_time",
)


def _normalise_timestamp(value: Any) -> str | None:
    if value in (None, ""):
        return None
    parsed = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _walk_json_ld(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        graph = value.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                yield from _walk_json_ld(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_json_ld(item)


def timestamp_from_raw(payload: dict[str, Any]) -> tuple[str, str, float] | None:
    for key in RAW_KEYS:
        timestamp = _normalise_timestamp(payload.get(key))
        if timestamp:
            return timestamp, f"gdelt:{key}", 0.92
    event_date = str(payload.get("event_date") or "")
    if "T" in event_date or ":" in event_date:
        timestamp = _normalise_timestamp(event_date)
        if timestamp:
            return timestamp, "gdelt:event_date", 0.85
    return None


def timestamp_from_article(url: str, timeout: int = 12) -> tuple[str, str, float] | None:
    if not url:
        return None
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
        timeout=timeout,
        allow_redirects=True,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            payload = json.loads(script.string or script.get_text() or "null")
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        for item in _walk_json_ld(payload):
            for key in ("datePublished", "dateCreated", "uploadDate"):
                timestamp = _normalise_timestamp(item.get(key))
                if timestamp:
                    confidence = 0.98 if key == "datePublished" else 0.90
                    return timestamp, f"article:jsonld:{key}", confidence

    for key in META_KEYS:
        tag = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
        if tag:
            timestamp = _normalise_timestamp(tag.get("content"))
            if timestamp:
                return timestamp, f"article:meta:{key}", 0.96

    for tag in soup.find_all("time"):
        timestamp = _normalise_timestamp(tag.get("datetime"))
        if timestamp:
            return timestamp, "article:time", 0.82
    return None


def enrich_event_timestamp(event: MarketEvent) -> MarketEvent:
    result = timestamp_from_raw(event.raw)
    if result is None and event.url:
        try:
            result = timestamp_from_article(event.url)
        except requests.RequestException:
            result = None

    if result:
        event.published_at, event.timestamp_source, event.timestamp_confidence = result
    return event


def enrich_event_timestamps(events: Iterable[MarketEvent]) -> list[MarketEvent]:
    return [enrich_event_timestamp(event) for event in events]
