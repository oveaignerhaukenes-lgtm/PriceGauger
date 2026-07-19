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
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        return None
    value = metrics.get(name)
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


def _actors(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("actors") or []
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return []

    names: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            value = item.get("name") or item.get("label") or item.get("actor")
        elif isinstance(item, str):
            value = item
        else:
            value = None
        name = str(value or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def _geo(payload: dict[str, Any]) -> dict[str, Any]:
    geo = payload.get("geo")
    if isinstance(geo, dict):
        return geo
    return {}


def market_event_from_gdelt(payload: dict[str, Any]) -> MarketEvent:
    if not isinstance(payload, dict):
        raise TypeError(f"GDELT event must be a mapping, got {type(payload).__name__}")

    geo = _geo(payload)
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
        actors=_actors(payload),
        confidence=_metric(payload, "confidence"),
        market_sensitivity=_metric(payload, "market_sensitivity"),
        significance=_metric(payload, "significance"),
        url=str(payload.get("url") or payload.get("primary_story_url") or ""),
        raw=payload,
        published_at=published_at,
        timestamp_source="gdelt:payload" if published_at else None,
        timestamp_confidence=0.90 if published_at else None,
    )
