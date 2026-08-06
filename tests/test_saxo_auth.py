from __future__ import annotations

from datetime import datetime, timedelta, timezone

from database import connect
from saxo_auth import (
    SaxoDatabaseTokenStore,
    SaxoOAuthClient,
    SaxoOAuthConfig,
    SaxoTokenRecord,
    SaxoTokenStore,
    configured_oauth_client,
)


class FakeResponse:
    ok = True
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def post(self, url, *, data, auth, headers, timeout):
        self.calls.append({"url": url, "data": data, "auth": auth, "headers": headers, "timeout": timeout})
        return FakeResponse(self.payload)


def config(tmp_path):
    return SaxoOAuthConfig(
        client_id="app-key",
        client_secret="app-secret",
        redirect_uri="http://localhost:8501/Saxo_OpenAPI",
        environment="sim",
        token_path=str(tmp_path / "tokens.json"),
    )


def token_record(*, access_token="access", refresh_token="refresh", environment="sim"):
    now = datetime.now(timezone.utc)
    return SaxoTokenRecord(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="Bearer",
        access_expires_at=(now + timedelta(minutes=10)).isoformat(),
        refresh_expires_at=(now + timedelta(hours=1)).isoformat(),
        environment=environment,
        updated_at=now.isoformat(),
    )


def test_exchange_code_persists_rotating_token_pair(tmp_path):
    session = FakeSession(
        {
            "access_token": "access-1",
            "refresh_token": "refresh-1",
            "token_type": "Bearer",
            "expires_in": 1200,
            "refresh_token_expires_in": 3600,
        }
    )
    client = SaxoOAuthClient(config(tmp_path), session=session)

    record = client.exchange_code("authorization-code")

    assert record.access_token == "access-1"
    assert client.store.load().refresh_token == "refresh-1"
    assert session.calls[0]["data"]["grant_type"] == "authorization_code"
    assert session.calls[0]["auth"] == ("app-key", "app-secret")


def test_access_token_refreshes_before_expiry_and_replaces_refresh_token(tmp_path):
    cfg = config(tmp_path)
    store = SaxoTokenStore(cfg.token_path)
    now = datetime.now(timezone.utc)
    store.save(
        SaxoTokenRecord(
            access_token="expired-access",
            refresh_token="refresh-old",
            token_type="Bearer",
            access_expires_at=(now + timedelta(seconds=10)).isoformat(),
            refresh_expires_at=(now + timedelta(hours=1)).isoformat(),
            environment="sim",
            updated_at=now.isoformat(),
        )
    )
    session = FakeSession(
        {
            "access_token": "access-new",
            "refresh_token": "refresh-new",
            "token_type": "Bearer",
            "expires_in": 1200,
            "refresh_token_expires_in": 3600,
        }
    )
    client = SaxoOAuthClient(cfg, store=store, session=session)

    assert client.access_token() == "access-new"
    assert store.load().refresh_token == "refresh-new"
    assert session.calls[0]["data"] == {
        "grant_type": "refresh_token",
        "refresh_token": "refresh-old",
        "redirect_uri": cfg.redirect_uri,
    }


def test_valid_access_token_does_not_call_token_endpoint(tmp_path):
    cfg = config(tmp_path)
    store = SaxoTokenStore(cfg.token_path)
    now = datetime.now(timezone.utc)
    store.save(
        SaxoTokenRecord(
            access_token="still-valid",
            refresh_token="refresh",
            token_type="Bearer",
            access_expires_at=(now + timedelta(minutes=10)).isoformat(),
            refresh_expires_at=(now + timedelta(hours=1)).isoformat(),
            environment="sim",
            updated_at=now.isoformat(),
        )
    )
    session = FakeSession({})
    client = SaxoOAuthClient(cfg, store=store, session=session)

    assert client.access_token() == "still-valid"
    assert session.calls == []


def test_database_token_store_is_shared_and_supports_rotating_tokens(tmp_path):
    db_path = tmp_path / "shared-tokens.sqlite3"
    factory = lambda: connect(db_path, force_sqlite=True)
    web_store = SaxoDatabaseTokenStore("sim", connection_factory=factory)
    worker_store = SaxoDatabaseTokenStore("sim", connection_factory=factory)

    web_store.save(token_record(access_token="web-access", refresh_token="refresh-1"))
    assert worker_store.load().access_token == "web-access"

    worker_store.save(token_record(access_token="worker-access", refresh_token="refresh-2"))
    assert web_store.load().refresh_token == "refresh-2"

    web_store.clear()
    assert worker_store.load() is None


def test_database_token_store_keeps_sim_and_live_separate(tmp_path):
    db_path = tmp_path / "environment-tokens.sqlite3"
    factory = lambda: connect(db_path, force_sqlite=True)
    sim_store = SaxoDatabaseTokenStore("sim", connection_factory=factory)
    live_store = SaxoDatabaseTokenStore("live", connection_factory=factory)

    sim_store.save(token_record(access_token="sim-access"))
    live_store.save(token_record(access_token="live-access", environment="live"))

    assert sim_store.load().access_token == "sim-access"
    assert live_store.load().access_token == "live-access"


def test_configured_client_uses_database_store_when_database_url_exists(monkeypatch):
    values = {
        "SAXO_APP_KEY": "app-key",
        "SAXO_APP_SECRET": "app-secret",
        "SAXO_REDIRECT_URI": "https://example.test/Saxo_OpenAPI",
        "SAXO_ENVIRONMENT": "sim",
    }
    monkeypatch.setenv("DATABASE_URL", "postgresql://configured-but-not-opened")

    client = configured_oauth_client(lambda name: values.get(name, ""))

    assert isinstance(client.store, SaxoDatabaseTokenStore)
