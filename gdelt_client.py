from __future__ import annotations

import re
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
        prefix = stage
        if status_code is not None:
            prefix += f" · HTTP {status_code}"
        super().__init__(f"{prefix}: {message}")


@dataclass(slots=True)
class GdeltPage:
    events: list[MarketEvent]
    next_cursor: str | None
    warning: str | None = None


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

    @staticmethod
    def _semantic_timeout(exc: GdeltError) -> bool:
        text = str(exc).lower()
        return exc.status_code in {500, 502, 503, 504} and (
            "embedding" in text or "semantic search" in text
        )

    @staticmethod
    def _lexical_filter(items: list[dict[str, Any]], search: str, limit: int) -> list[dict[str, Any]]:
        terms = [
            term
            for term in re.findall(r"[a-z0-9]+", search.lower())
            if len(term) >= 3 and term not in {"the", "and", "for", "with", "from", "on", "in", "of", "to"}
        ]
        if not terms:
            return items[:limit]

        ranked: list[tuple[int, dict[str, Any]]] = []
        for item in items:
            haystack = " ".join(
                str(item.get(field) or "")
                for field in ("title", "summary", "category", "subcategory", "domain")
            ).lower()
            score = sum(term in haystack for term in terms)
            if score:
                ranked.append((score, item))
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in ranked[:limit]] if ranked else items[:limit]

    def _parse_page(self, payload: dict[str, Any], *, warning: str | None = None) -> GdeltPage:
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
        return GdeltPage(events=events, next_cursor=pagination.get("next_cursor"), warning=warning)

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
        bounded_limit = max(1, min(limit, 100))
        params = {
            "date_start": date_start,
            "date_end": date_end,
            "search": search,
            "country": country,
            "category": category,
            "domain": domain,
            "event_family": event_family,
            "confidence_profile": confidence_profile,
            "sort": sort,
            "limit": bounded_limit,
            "cursor": cursor,
        }

        try:
            payload = self._get("/events", params)
            return self._parse_page(payload)
        except GdeltError as exc:
            if not search.strip() or not self._semantic_timeout(exc):
                raise

        fallback_params = dict(params)
        fallback_params.pop("search", None)
        fallback_params.pop("cursor", None)
        fallback_params["limit"] = 100
        payload = self._get("/events", fallback_params)
        raw_events = payload.get("data")
        if isinstance(raw_events, list):
            valid_items = [item for item in raw_events if isinstance(item, dict)]
            payload = dict(payload)
            payload["data"] = self._lexical_filter(valid_items, search, bounded_limit)
            payload["pagination"] = {}

        warning = (
            "GDELTs semantiske søk fikk tidsavbrudd. PriceGauger hentet derfor hendelser med "
            "dato-/land-/domenefiltrene og brukte et lokalt nøkkelordfilter. Resultatene er brukbare, "
            "men mindre presise enn et vellykket semantisk søk."
        )
        return self._parse_page(payload, warning=warning)
