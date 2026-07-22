from __future__ import annotations

from typing import Any

import requests

from event_models import market_event_from_gdelt
from gdelt_types import GdeltError, GdeltPage

BASE_URL = "https://gdeltcloud.com/api/v2"
DIRECT_SENTINEL = "__DIRECT__"


class GdeltClient:
    """Compatibility facade used by Event Lab.

    Passing ``__DIRECT__`` selects the free official GDELT DOC 2.0 API.
    Any other non-empty value is treated as a GDELT Cloud bearer token.
    """

    def __init__(self, api_key: str, timeout: int = 30) -> None:
        if not api_key:
            raise ValueError("GDELT provider configuration is missing")
        self._api_key = api_key
        self._timeout = timeout
        self._direct = api_key == DIRECT_SENTINEL

    def list_events(self, **kwargs) -> GdeltPage:
        if self._direct:
            from gdelt_direct_client import DirectGdeltClient

            return DirectGdeltClient(timeout=self._timeout).list_events(**kwargs)
        return self._list_cloud_events(**kwargs)

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        safe_params = {key: value for key, value in params.items() if value not in (None, "")}
        try:
            response = requests.get(
                f"{BASE_URL}{path}",
                params=safe_params,
                headers={"Authorization": f"Bearer {self._api_key}", "User-Agent": "PriceGauger/1.0-alpha"},
                timeout=self._timeout,
            )
            payload = response.json()
        except requests.Timeout as exc:
            raise GdeltError(f"Tidsavbrudd etter {self._timeout} sekunder.", stage="nettverk") from exc
        except requests.RequestException as exc:
            raise GdeltError("Kunne ikke opprette forbindelse til GDELT Cloud.", stage="nettverk") from exc
        except ValueError as exc:
            raise GdeltError("GDELT Cloud returnerte ugyldig JSON.", stage="respons") from exc
        if not isinstance(payload, dict):
            raise GdeltError("Forventet JSON-objekt fra GDELT Cloud.", stage="respons", status_code=response.status_code)
        if response.status_code >= 400 or payload.get("success") is False:
            message = payload.get("message") or payload.get("detail") or "GDELT request failed"
            raise GdeltError(str(message), stage="API", status_code=response.status_code)
        return payload

    def _parse_page(self, payload: dict[str, Any]) -> GdeltPage:
        raw_events = payload.get("data") or []
        if not isinstance(raw_events, list):
            raise GdeltError("Feltet 'data' var ikke en liste.", stage="parsing")
        events = [market_event_from_gdelt(item) for item in raw_events if isinstance(item, dict)]
        pagination = payload.get("pagination") if isinstance(payload.get("pagination"), dict) else {}
        return GdeltPage(events, pagination.get("next_cursor"))

    def _list_cloud_events(
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
                "limit": max(1, min(int(limit), 100)),
                "cursor": cursor,
            },
        )
        return self._parse_page(payload)
