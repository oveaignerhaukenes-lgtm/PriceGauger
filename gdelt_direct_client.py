from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha1
from typing import Any
from urllib.parse import urlparse

import requests

from event_models import MarketEvent
from gdelt_types import GdeltError, GdeltPage

DOC_API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"


def _gdelt_datetime(value: str, *, end_of_day: bool = False) -> str:
    parsed = datetime.fromisoformat(value[:10]).replace(tzinfo=timezone.utc)
    if end_of_day:
        parsed = parsed.replace(hour=23, minute=59, second=59)
    return parsed.strftime("%Y%m%d%H%M%S")


def _article_event(article: dict[str, Any]) -> MarketEvent:
    url = str(article.get("url") or "")
    title = str(article.get("title") or "")
    seen = str(article.get("seendate") or "")
    published_at = None
    event_date = ""
    if len(seen) >= 14 and seen[:14].isdigit():
        parsed = datetime.strptime(seen[:14], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        published_at = parsed.isoformat()
        event_date = parsed.date().isoformat()
    domain = str(article.get("domain") or urlparse(url).netloc)
    country = str(article.get("sourcecountry") or "")
    event_id = "gdelt-doc:" + sha1((url or title).encode("utf-8")).hexdigest()[:20]
    return MarketEvent(
        event_id=event_id,
        source="gdelt_doc_v2",
        event_date=event_date,
        title=title,
        summary=title,
        category="news_coverage",
        subcategory="article",
        domain=domain,
        country=country,
        location="",
        actors=[],
        confidence=None,
        market_sensitivity=None,
        significance=None,
        url=url,
        raw=article,
        published_at=published_at,
        timestamp_source="gdelt:seendate" if published_at else None,
        timestamp_confidence=0.85 if published_at else None,
    )


@dataclass(slots=True)
class DirectGdeltClient:
    timeout: int = 30

    def list_events(
        self,
        *,
        date_start: str,
        date_end: str,
        search: str = "",
        country: str = "",
        category: str = "",
        domain: str = "",
        event_family: str = "",
        confidence_profile: str = "precise",
        sort: str = "significance",
        limit: int = 50,
        cursor: str | None = None,
    ) -> GdeltPage:
        del category, event_family, confidence_profile, cursor
        query_parts = [search.strip() or "news"]
        if country.strip():
            query_parts.append(f'sourcecountry:"{country.strip()}"')
        if domain.strip():
            query_parts.append(f'domain:"{domain.strip()}"')
        params = {
            "query": " ".join(query_parts),
            "mode": "artlist",
            "format": "json",
            "maxrecords": max(1, min(int(limit), 250)),
            "startdatetime": _gdelt_datetime(date_start),
            "enddatetime": _gdelt_datetime(date_end, end_of_day=True),
            "sort": "datedesc" if sort in {"date", "datedesc"} else "hybridrel",
        }
        try:
            response = requests.get(
                DOC_API_URL,
                params=params,
                headers={"User-Agent": "PriceGauger/1.0-alpha"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.Timeout as exc:
            raise GdeltError("Tidsavbrudd mot gratis GDELT DOC API.", stage="nettverk") from exc
        except requests.RequestException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            raise GdeltError("Kunne ikke hente gratis GDELT DOC-data.", stage="nettverk", status_code=status) from exc
        except ValueError as exc:
            raise GdeltError("Gratis GDELT DOC returnerte ugyldig JSON.", stage="respons") from exc

        articles = payload.get("articles", []) if isinstance(payload, dict) else []
        if not isinstance(articles, list):
            raise GdeltError("Feltet 'articles' var ikke en liste.", stage="parsing")
        events = [_article_event(item) for item in articles if isinstance(item, dict)]
        warning = None
        if not events:
            warning = "Gratis GDELT DOC returnerte ingen artikler for dette søket og tidsvinduet."
        return GdeltPage(events=events, next_cursor=None, warning=warning)
