from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(slots=True)
class MarketEvent:
    event_id: str
    source: str
    event_date: str
    title: str
    summary: str
    category: str
    subcategory: str
    domain: str
    country: str
    location: str
    actors: list[str]
    confidence: float | None
    market_sensitivity: float | None
    significance: float | None
    url: str
    raw: dict[str, Any]
    published_at: str | None = None
    timestamp_source: str | None = None
    timestamp_confidence: float | None = None

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


def _metric(payload: dict[str, Any], name: str) -> float | None:
    value = (payload.get("metrics") or {}).get(name)
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _first_value(payload: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def market_event_from_gdelt(payload: dict[str, Any]) -> MarketEvent:
    geo = payload.get("geo") or {}
    actors = [str(item.get("name", "")).strip() for item in payload.get("actors", []) if item.get("name")]
    published_at = _first_value(
        payload,
        (
            "published_at",
            "publication_time",
            "publication_datetime",
            "created_at",
            "datetime",
            "timestamp",
            "event_time",
        ),
    )
    return MarketEvent(
        event_id=str(payload.get("id", "")),
        source="gdelt_cloud_v2",
        event_date=str(payload.get("event_date", "")),
        title=str(payload.get("title", "")),
        summary=str(payload.get("summary", "")),
        category=str(payload.get("category", "")),
        subcategory=str(payload.get("subcategory", "")),
        domain=str(payload.get("domain", "")),
        country=str(geo.get("country", "")),
        location=str(geo.get("location", "")),
        actors=actors,
        confidence=_metric(payload, "confidence"),
        market_sensitivity=_metric(payload, "market_sensitivity"),
        significance=_metric(payload, "significance"),
        url=str(payload.get("url") or payload.get("primary_story_url") or ""),
        raw=payload,
        published_at=published_at,
        timestamp_source="gdelt:payload" if published_at else None,
        timestamp_confidence=0.90 if published_at else None,
    )
