from __future__ import annotations

from dataclasses import dataclass

import pytest
import requests

import gdelt_direct_client
from gdelt_direct_client import DirectGdeltClient, _article_event
from gdelt_types import GdeltError


@dataclass
class FakeResponse:
    status_code: int
    payload: dict
    headers: dict[str, str] | None = None

    def __post_init__(self):
        if self.headers is None:
            self.headers = {}

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError(f"HTTP {self.status_code}")
            error.response = self
            raise error

    def json(self):
        return self.payload


def test_article_event_parses_actual_gdelt_seen_date_format():
    event = _article_event(
        {
            "url": "https://example.com/story",
            "title": "Iran oil terminal disrupted",
            "seendate": "20260725T010000Z",
            "domain": "example.com",
            "sourcecountry": "China",
        }
    )

    assert event.published_at == "2026-07-25T01:00:00+00:00"
    assert event.event_date == "2026-07-25"
    assert event.timestamp_source == "gdelt:seendate"


def test_country_is_event_term_not_sourcecountry_filter(monkeypatch):
    captured = {}

    def fake_get(url, *, params, headers, timeout):
        captured.update({"url": url, "params": params, "headers": headers, "timeout": timeout})
        return FakeResponse(200, {"articles": []})

    monkeypatch.setattr(gdelt_direct_client, "_wait_for_request_slot", lambda: None)
    monkeypatch.setattr(gdelt_direct_client.requests, "get", fake_get)

    DirectGdeltClient(timeout=12).list_events(
        date_start="2026-07-01",
        date_end="2026-07-25",
        search="attack energy infrastructure",
        country="Iran",
        limit=5,
    )

    query = captured["params"]["query"]
    assert query == 'attack energy infrastructure "Iran"'
    assert "sourcecountry" not in query
    assert captured["timeout"] == 12


def test_country_is_not_duplicated_when_already_in_search(monkeypatch):
    captured = {}

    def fake_get(url, *, params, headers, timeout):
        del url, headers, timeout
        captured.update(params)
        return FakeResponse(200, {"articles": []})

    monkeypatch.setattr(gdelt_direct_client, "_wait_for_request_slot", lambda: None)
    monkeypatch.setattr(gdelt_direct_client.requests, "get", fake_get)

    DirectGdeltClient().list_events(
        date_start="2026-07-01",
        date_end="2026-07-25",
        search="Iran oil terminal attack",
        country="Iran",
    )

    assert captured["query"] == "Iran oil terminal attack"


def test_http_429_waits_and_retries_once(monkeypatch):
    responses = [
        FakeResponse(429, {}, headers={"Retry-After": "7"}),
        FakeResponse(
            200,
            {
                "articles": [
                    {
                        "url": "https://example.com/story",
                        "title": "Iran oil terminal disrupted",
                        "seendate": "20260725T010000Z",
                        "domain": "example.com",
                        "sourcecountry": "China",
                    }
                ]
            },
        ),
    ]
    sleeps: list[float] = []

    monkeypatch.setattr(gdelt_direct_client, "_wait_for_request_slot", lambda: None)
    monkeypatch.setattr(gdelt_direct_client.time, "sleep", sleeps.append)
    monkeypatch.setattr(gdelt_direct_client.requests, "get", lambda *args, **kwargs: responses.pop(0))

    page = DirectGdeltClient().list_events(
        date_start="2026-07-01",
        date_end="2026-07-25",
        search="Iran oil terminal attack",
    )

    assert len(page.events) == 1
    assert sleeps == [7.0]


def test_second_http_429_raises_clear_error(monkeypatch):
    responses = [FakeResponse(429, {}), FakeResponse(429, {})]

    monkeypatch.setattr(gdelt_direct_client, "_wait_for_request_slot", lambda: None)
    monkeypatch.setattr(gdelt_direct_client.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(gdelt_direct_client.requests, "get", lambda *args, **kwargs: responses.pop(0))

    with pytest.raises(GdeltError, match="ratebegrenset"):
        DirectGdeltClient().list_events(
            date_start="2026-07-01",
            date_end="2026-07-25",
            search="Iran oil terminal attack",
        )
