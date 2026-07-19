from __future__ import annotations

import json
from datetime import timezone
from typing import Any, Iterable
from urllib.parse import urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup

from event_models import MarketEvent

USER_AGENT = "PriceGauger/0.8 (+timestamp enrichment)"
META_KEYS = (
    "article:published_time",
    "article:published",
    "og:published_time",
    "datePublished",
    "datepublished",
    "publish-date",
    "pubdate",
    "publication_date",
    "parsely-pub-date",
    "sailthru.date",
    "dc.date",
    "dc.date.issued",
    "date.issued",
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
    "precise_pub_timestamp",
    "precisepubtimestamp",
)


def _normalise_timestamp(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if len(text) == 14 and text.isdigit():
        text = f"{text[:4]}-{text[4:6]}-{text[6:8]}T{text[8:10]}:{text[10:12]}:{text[12:14]}Z"
    parsed = pd.to_datetime(text, utc=True, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _walk_json(value: Any) -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key), child
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _walk_json_ld(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json_ld(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json_ld(child)


def timestamp_from_raw(payload: dict[str, Any]) -> tuple[str, str, float] | None:
    wanted = {key.lower() for key in RAW_KEYS}
    for key, value in _walk_json(payload):
        if key.lower() in wanted:
            timestamp = _normalise_timestamp(value)
            if timestamp:
                return timestamp, f"gdelt:{key}", 0.92
    event_date = str(payload.get("event_date") or "")
    if "T" in event_date or ":" in event_date:
        timestamp = _normalise_timestamp(event_date)
        if timestamp:
            return timestamp, "gdelt:event_date", 0.85
    return None


def _is_gdelt_page(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return host.endswith("gdeltcloud.com") or host.endswith("gdeltproject.org")


def article_urls_from_event(event: MarketEvent) -> list[str]:
    candidates: list[str] = []
    raw = event.raw if isinstance(event.raw, dict) else {}

    for article in raw.get("top_articles") or []:
        if isinstance(article, dict) and article.get("url"):
            candidates.append(str(article["url"]))

    for key, value in _walk_json(raw):
        if key.lower() in {"article_url", "source_url", "document_url"} and isinstance(value, str):
            candidates.append(value)

    if event.url and not _is_gdelt_page(event.url):
        candidates.append(event.url)

    unique: list[str] = []
    seen: set[str] = set()
    for url in candidates:
        url = url.strip()
        if url.startswith(("http://", "https://")) and url not in seen:
            unique.append(url)
            seen.add(url)
    return unique


def timestamp_from_article(url: str, timeout: int = 12) -> tuple[str, str, float] | None:
    response = requests.get(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.8",
        },
        timeout=timeout,
        allow_redirects=True,
    )
    response.raise_for_status()
    content_type = response.headers.get("content-type", "").lower()
    if "html" not in content_type and "xhtml" not in content_type:
        return None

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

    itemprop = soup.find(attrs={"itemprop": "datePublished"})
    if itemprop:
        timestamp = _normalise_timestamp(itemprop.get("content") or itemprop.get("datetime") or itemprop.get_text(strip=True))
        if timestamp:
            return timestamp, "article:itemprop:datePublished", 0.94

    for tag in soup.find_all("time"):
        timestamp = _normalise_timestamp(tag.get("datetime") or tag.get("content"))
        if timestamp:
            return timestamp, "article:time", 0.82
    return None


def enrich_event_timestamp(event: MarketEvent) -> MarketEvent:
    event.raw.pop("_timestamp_diagnostic", None)
    event.raw.pop("_timestamp_article_url", None)

    result = timestamp_from_raw(event.raw)
    if result:
        event.published_at, event.timestamp_source, event.timestamp_confidence = result
        event.raw["_timestamp_diagnostic"] = "found_in_gdelt_payload"
        return event

    urls = article_urls_from_event(event)
    if not urls:
        event.raw["_timestamp_diagnostic"] = "no_source_article_url"
        return event

    failures: list[str] = []
    for url in urls:
        try:
            result = timestamp_from_article(url)
        except requests.Timeout:
            failures.append("timeout")
            continue
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            failures.append(f"http_{status}")
            continue
        except requests.RequestException:
            failures.append("request_error")
            continue

        if result:
            event.published_at, event.timestamp_source, event.timestamp_confidence = result
            event.raw["_timestamp_article_url"] = url
            event.raw["_timestamp_diagnostic"] = "found_in_source_article"
            return event
        failures.append("no_time_metadata")

    event.raw["_timestamp_diagnostic"] = ", ".join(dict.fromkeys(failures)) or "not_found"
    event.raw["_timestamp_article_url"] = urls[0]
    return event


def enrich_event_timestamps(events: Iterable[MarketEvent]) -> list[MarketEvent]:
    return [enrich_event_timestamp(event) for event in events]
