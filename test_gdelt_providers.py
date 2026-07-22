from __future__ import annotations

from gdelt_client import DIRECT_SENTINEL, GdeltClient
from gdelt_direct_client import DirectGdeltClient


def test_direct_sentinel_routes_to_official_client(monkeypatch):
    captured = {}

    def fake_list(self, **kwargs):
        captured.update(kwargs)
        return "direct-result"

    monkeypatch.setattr(DirectGdeltClient, "list_events", fake_list)
    result = GdeltClient(DIRECT_SENTINEL).list_events(
        date_start="2026-07-01",
        date_end="2026-07-22",
        search="missile attack",
        limit=25,
    )
    assert result == "direct-result"
    assert captured["search"] == "missile attack"
    assert captured["limit"] == 25


def test_cloud_key_does_not_select_direct():
    client = GdeltClient("cloud-secret")
    assert client._direct is False
