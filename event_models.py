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

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


def _metric(payload: dict[str, Any], name: str) -> float | None:
    value = (payload.get("metrics") or {}).get(name)
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def market_event_from_gdelt(payload: dict[str, Any]) -> MarketEvent:
    geo = payload.get("geo") or {}
    actors = [str(item.get("name", "")).strip() for item in payload.get("actors", []) if item.get("name")]
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
    )
