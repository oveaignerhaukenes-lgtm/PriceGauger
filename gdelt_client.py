from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from event_models import MarketEvent, market_event_from_gdelt

BASE_URL = "https://gdeltcloud.com/api/v2"


class GdeltError(RuntimeError):
    """Safe, user-displayable GDELT failure with no credentials or full request URL."""

    def __init__(self, message: str, *, stage: str, status_code: int | None = None) -> None:
        self.stage = stage
        self.status_code = status_code
        prefix = f"{stage}"
        if status_code is not None:
            prefix += f" · HTTP {status_code}"
        super().__init__(f"{prefix}: {message}")


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
        safe_params = {key: value for key, value in params.items() if value not in (None, "")}
        try:
            response = requests.get(
                f"{BASE_URL}{path}",
                params=safe_params,
                headers={"Authorization": f"Bearer {self._api_key}", "User-Agent": "PriceGauger/1.0-alpha"},
                timeout=self._timeout,
            )
        except requests.Timeout as exc:
            raise GdeltError(
                f"Tidsavbrudd etter {self._timeout} sekunder. Prøv igjen.",
                stage="nettverk",
            ) from exc
        except requests.ConnectionError as exc:
            raise GdeltError(
                "Kunne ikke opprette forbindelse til GDELT Cloud.",
                stage="nettverk",
            ) from exc
        except requests.RequestException as exc:
            raise GdeltError(
                f"{type(exc).__name__}: forespørselen kunne ikke fullføres.",
                stage="nettverk",
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            content_type = response.headers.get("content-type", "ukjent")
            raise GdeltError(
                f"Svaret var ikke gyldig JSON (content-type: {content_type}).",
                stage="respons",
                status_code=response.status_code,
            ) from exc

        if not isinstance(payload, dict):
            raise GdeltError(
                f"Forventet JSON-objekt, fikk {type(payload).__name__}.",
                stage="respons",
                status_code=response.status_code,
            )

        if response.status_code >= 400 or payload.get("success") is False:
            code = payload.get("error") or payload.get("code") or f"HTTP_{response.status_code}"
            message = payload.get("message") or payload.get("detail") or "GDELT request failed"
            raise GdeltError(
                f"{code}: {message}",
                stage="API",
                status_code=response.status_code,
            )
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

        raw_events = payload.get("data", [])
        if raw_events is None:
            raw_events = []
        if not isinstance(raw_events, list):
            raise GdeltError(
                f"Feltet 'data' hadde typen {type(raw_events).__name__}, ikke liste.",
                stage="parsing",
            )

        events: list[MarketEvent] = []
        skipped = 0
        for index, item in enumerate(raw_events):
            if not isinstance(item, dict):
                skipped += 1
                continue
            try:
                events.append(market_event_from_gdelt(item))
            except Exception as exc:
                raise GdeltError(
                    f"Kunne ikke tolke hendelse {index + 1}: {type(exc).__name__}: {exc}",
                    stage="parsing",
                ) from exc

        pagination = payload.get("pagination") or {}
        if not isinstance(pagination, dict):
            pagination = {}
        if skipped and not events:
            raise GdeltError(
                f"Alle {skipped} returnerte poster hadde ugyldig format.",
                stage="parsing",
            )
        return GdeltPage(events=events, next_cursor=pagination.get("next_cursor"))
