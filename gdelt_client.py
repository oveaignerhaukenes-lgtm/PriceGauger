from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from event_models import MarketEvent, market_event_from_gdelt

BASE_URL = "https://gdeltcloud.com/api/v2"


class GdeltError(RuntimeError):
    pass


@dataclass(slots=True)
class GdeltPage:
    events: list[MarketEvent]
    next_cursor: str | None


class GdeltClient:
    def __init__(self, api_key: str, timeout: int = 30) -> None:
        if not api_key:
            raise ValueError("GDELT API key is missing")
        self._api_key = api_key
        self._timeout = timeout

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        response = requests.get(
            f"{BASE_URL}{path}",
            params={key: value for key, value in params.items() if value not in (None, "")},
            headers={"Authorization": f"Bearer {self._api_key}", "User-Agent": "PriceGauger/0.6"},
            timeout=self._timeout,
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise GdeltError(f"GDELT returned invalid JSON (HTTP {response.status_code})") from exc
        if response.status_code >= 400 or payload.get("success") is False:
            code = payload.get("error") or payload.get("code") or f"HTTP_{response.status_code}"
            message = payload.get("message") or "GDELT request failed"
            raise GdeltError(f"{code}: {message}")
        return payload

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
        payload = self._get(
            "/events",
            {
                "date_start": date_start,
                "date_end": date_end,
                "search": search,
                "country": country,
                "category": category,
                "domain": domain,
                "event_family": event_family,
                "confidence_profile": confidence_profile,
                "sort": sort,
                "limit": max(1, min(limit, 100)),
                "cursor": cursor,
            },
        )
        events = [market_event_from_gdelt(item) for item in payload.get("data", [])]
        pagination = payload.get("pagination") or {}
        return GdeltPage(events=events, next_cursor=pagination.get("next_cursor"))
