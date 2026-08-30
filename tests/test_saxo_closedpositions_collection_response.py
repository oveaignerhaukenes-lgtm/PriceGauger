from __future__ import annotations

import pytest

from saxo_provider import SaxoClient, SaxoError


class _Response:
    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.ok = status_code < 400

    def json(self):
        return self._payload


class _Session:
    def __init__(self, payload):
        self.payload = payload
        self.headers = {}

    def get(self, url, params=None, timeout=None):
        return _Response(self.payload)


def test_closed_positions_endpoint_normalizes_bare_json_list_to_data_envelope():
    rows = [{"ClosedPositionUniqueId": "closed-1"}]
    client = SaxoClient("token", session=_Session(rows))

    payload = client._get("port/v1/closedpositions", params={"AccountKey": "key"})

    assert payload == {"Data": rows}


def test_other_endpoints_keep_strict_json_object_contract():
    client = SaxoClient("token", session=_Session([]))

    with pytest.raises(SaxoError, match="forventet JSON-objekt"):
        client._get("port/v1/accounts/me")


def test_closed_positions_still_rejects_non_collection_scalar_json():
    client = SaxoClient("token", session=_Session("unexpected"))

    with pytest.raises(SaxoError, match="forventet JSON-objekt"):
        client._get("port/v1/closedpositions")
