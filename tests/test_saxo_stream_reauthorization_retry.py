from __future__ import annotations

from types import SimpleNamespace

from saxo_streaming import try_reauthorize_stream


def test_try_reauthorize_stream_keeps_socket_alive_on_transient_refresh_failure():
    class Client:
        base_url = "https://gateway.saxobank.com/sim/openapi"
        timeout = 20.0

        def __init__(self) -> None:
            self.session = SimpleNamespace(headers={})

        def _set_authorization(self, *, force_refresh: bool = False) -> None:
            assert force_refresh is True
            raise TimeoutError("temporary token timeout")

    assert try_reauthorize_stream(Client(), context_id="pg-test") is False


def test_try_reauthorize_stream_reports_success_when_authorize_accepts_token():
    class Session:
        def __init__(self) -> None:
            self.headers: dict[str, str] = {}

        def put(self, url: str, *, timeout: float):
            return SimpleNamespace(status_code=202)

    class Client:
        base_url = "https://gateway.saxobank.com/sim/openapi"
        timeout = 20.0

        def __init__(self) -> None:
            self.session = Session()

        def _set_authorization(self, *, force_refresh: bool = False) -> None:
            assert force_refresh is True
            self.session.headers["Authorization"] = "Bearer refreshed"

    assert try_reauthorize_stream(Client(), context_id="pg-test") is True
