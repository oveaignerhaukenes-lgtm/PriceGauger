from __future__ import annotations

import json
import os
import secrets
import threading
from contextlib import contextmanager, nullcontext
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, ContextManager, Iterator, Protocol
from urllib.parse import urlencode

import requests


SIM_AUTH_BASE_URL = "https://sim.logonvalidation.net"
LIVE_AUTH_BASE_URL = "https://live.logonvalidation.net"


class SaxoAuthError(RuntimeError):
    """Authentication failure that is safe to show without exposing credentials."""

    def __init__(self, message: str, *, status: str = "AUTH_FAILED", status_code: int | None = None) -> None:
        self.status = status
        self.status_code = status_code
        prefix = status
        if status_code is not None:
            prefix += f" · HTTP {status_code}"
        super().__init__(f"{prefix}: {message}")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@dataclass(frozen=True, slots=True)
class SaxoOAuthConfig:
    client_id: str
    client_secret: str
    redirect_uri: str
    environment: str = "sim"
    auth_base_url: str = ""
    token_path: str = ""
    timeout: float = 20.0

    def __post_init__(self) -> None:
        environment = self.environment.strip().lower()
        if environment not in {"sim", "live"}:
            raise ValueError("SAXO_ENVIRONMENT må være 'sim' eller 'live'")
        object.__setattr__(self, "environment", environment)
        if not self.client_id.strip():
            raise ValueError("SAXO_APP_KEY mangler")
        if not self.client_secret.strip():
            raise ValueError("SAXO_APP_SECRET mangler")
        if not self.redirect_uri.strip():
            raise ValueError("SAXO_REDIRECT_URI mangler")
        if not self.auth_base_url:
            default = LIVE_AUTH_BASE_URL if environment == "live" else SIM_AUTH_BASE_URL
            object.__setattr__(self, "auth_base_url", default)
        if not self.token_path:
            object.__setattr__(self, "token_path", f"data/saxo_tokens_{environment}.json")

    @property
    def authorization_url(self) -> str:
        return f"{self.auth_base_url.rstrip('/')}/authorize"

    @property
    def token_url(self) -> str:
        return f"{self.auth_base_url.rstrip('/')}/token"


@dataclass(frozen=True, slots=True)
class SaxoTokenRecord:
    access_token: str
    refresh_token: str
    token_type: str
    access_expires_at: str
    refresh_expires_at: str | None
    environment: str
    updated_at: str

    @property
    def access_expiry(self) -> datetime:
        value = _parse_datetime(self.access_expires_at)
        if value is None:
            raise SaxoAuthError("access-token mangler utløpstid", status="TOKEN_STORE_INVALID")
        return value

    @property
    def refresh_expiry(self) -> datetime | None:
        return _parse_datetime(self.refresh_expires_at)

    def access_is_valid(self, *, leeway_seconds: int = 90) -> bool:
        return bool(self.access_token) and self.access_expiry > _utc_now() + timedelta(seconds=leeway_seconds)

    def refresh_is_valid(self, *, leeway_seconds: int = 30) -> bool:
        expiry = self.refresh_expiry
        return bool(self.refresh_token) and (expiry is None or expiry > _utc_now() + timedelta(seconds=leeway_seconds))


class SaxoTokenStoreProtocol(Protocol):
    def load(self) -> SaxoTokenRecord | None: ...

    def save(self, record: SaxoTokenRecord) -> None: ...

    def clear(self) -> None: ...

    def refresh_guard(self) -> ContextManager[None]: ...


class SaxoTokenStore:
    """Small atomic JSON token store. The file must live outside version control."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()
        self._lock = threading.RLock()

    def load(self) -> SaxoTokenRecord | None:
        with self._lock:
            if not self.path.exists():
                return None
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
                return SaxoTokenRecord(**payload)
            except (OSError, ValueError, TypeError) as exc:
                raise SaxoAuthError("tokenlageret kunne ikke leses", status="TOKEN_STORE_INVALID") from exc

    def save(self, record: SaxoTokenRecord) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_text(json.dumps(asdict(record), indent=2), encoding="utf-8")
            try:
                os.chmod(temporary, 0o600)
            except OSError:
                pass
            temporary.replace(self.path)
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass

    def clear(self) -> None:
        with self._lock:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass

    def refresh_guard(self) -> ContextManager[None]:
        return nullcontext()


class SaxoDatabaseTokenStore:
    """Shared Saxo token store for the Railway web and worker services.

    PostgreSQL advisory locking serializes refresh-token rotation across service
    processes. The same implementation can use an isolated SQLite connection in
    tests, where the process lock provides equivalent local serialization.
    """

    _POSTGRES_REFRESH_LOCK = 1_397_311_311

    def __init__(
        self,
        environment: str,
        *,
        connection_factory: Callable[[], ContextManager[Any]] | None = None,
    ) -> None:
        self.environment = environment
        self._connection_factory = connection_factory or self._default_connection_factory
        self._local = threading.local()
        self._lock = threading.RLock()

    @staticmethod
    def _default_connection_factory():
        from database import connect

        return connect()

    @staticmethod
    def _ensure_schema(db: Any) -> None:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS saxo_oauth_tokens (
                environment TEXT PRIMARY KEY,
                access_token TEXT NOT NULL,
                refresh_token TEXT NOT NULL,
                token_type TEXT NOT NULL,
                access_expires_at TEXT NOT NULL,
                refresh_expires_at TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        active = getattr(self._local, "connection", None)
        if active is not None:
            yield active
            return
        with self._connection_factory() as db:
            self._ensure_schema(db)
            yield db

    def load(self) -> SaxoTokenRecord | None:
        with self._lock, self._connection() as db:
            row = db.execute(
                """
                SELECT access_token, refresh_token, token_type, access_expires_at,
                       refresh_expires_at, environment, updated_at
                FROM saxo_oauth_tokens
                WHERE environment = ?
                """,
                (self.environment,),
            ).fetchone()
            if row is None:
                return None
            try:
                return SaxoTokenRecord(**dict(row))
            except (ValueError, TypeError) as exc:
                raise SaxoAuthError(
                    "tokenlageret kunne ikke leses",
                    status="TOKEN_STORE_INVALID",
                ) from exc

    def save(self, record: SaxoTokenRecord) -> None:
        if record.environment != self.environment:
            raise SaxoAuthError(
                "tokenet tilhører et annet Saxo-miljø",
                status="TOKEN_ENVIRONMENT_MISMATCH",
            )
        with self._lock, self._connection() as db:
            db.execute(
                """
                INSERT INTO saxo_oauth_tokens (
                    environment, access_token, refresh_token, token_type,
                    access_expires_at, refresh_expires_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(environment) DO UPDATE SET
                    access_token = excluded.access_token,
                    refresh_token = excluded.refresh_token,
                    token_type = excluded.token_type,
                    access_expires_at = excluded.access_expires_at,
                    refresh_expires_at = excluded.refresh_expires_at,
                    updated_at = excluded.updated_at
                """,
                (
                    record.environment,
                    record.access_token,
                    record.refresh_token,
                    record.token_type,
                    record.access_expires_at,
                    record.refresh_expires_at,
                    record.updated_at,
                ),
            )

    def clear(self) -> None:
        with self._lock, self._connection() as db:
            db.execute(
                "DELETE FROM saxo_oauth_tokens WHERE environment = ?",
                (self.environment,),
            )

    @contextmanager
    def refresh_guard(self) -> Iterator[None]:
        with self._lock:
            active = getattr(self._local, "connection", None)
            if active is not None:
                yield
                return
            with self._connection_factory() as db:
                self._ensure_schema(db)
                if getattr(db, "is_postgres", False):
                    lock_key = self._POSTGRES_REFRESH_LOCK + (1 if self.environment == "live" else 0)
                    db.execute("SELECT pg_advisory_xact_lock(?)", (lock_key,))
                self._local.connection = db
                try:
                    yield
                finally:
                    del self._local.connection


class SaxoOAuthClient:
    def __init__(
        self,
        config: SaxoOAuthConfig,
        *,
        store: SaxoTokenStoreProtocol | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.config = config
        self.store = store or SaxoTokenStore(config.token_path)
        self.session = session or requests.Session()
        self._refresh_lock = threading.RLock()

    def build_authorization_url(self, state: str | None = None) -> tuple[str, str]:
        oauth_state = state or secrets.token_urlsafe(32)
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self.config.client_id,
                "state": oauth_state,
                "redirect_uri": self.config.redirect_uri,
            }
        )
        return f"{self.config.authorization_url}?{query}", oauth_state

    def exchange_code(self, code: str) -> SaxoTokenRecord:
        if not code.strip():
            raise SaxoAuthError("authorization code mangler", status="CODE_MISSING")
        with self._refresh_lock, self.store.refresh_guard():
            return self._request_token(
                {
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.config.redirect_uri,
                }
            )

    def refresh(self, refresh_token: str | None = None) -> SaxoTokenRecord:
        with self._refresh_lock, self.store.refresh_guard():
            current = self.store.load()
            token = refresh_token or (current.refresh_token if current else "")
            if not token:
                raise SaxoAuthError("refresh-token mangler", status="REAUTH_REQUIRED")
            if current and not current.refresh_is_valid():
                raise SaxoAuthError("refresh-token er utløpt", status="REAUTH_REQUIRED")
            return self._request_token(
                {
                    "grant_type": "refresh_token",
                    "refresh_token": token,
                    "redirect_uri": self.config.redirect_uri,
                }
            )

    def access_token(self, *, force_refresh: bool = False) -> str:
        with self._refresh_lock:
            current = self.store.load()
            if current is None:
                raise SaxoAuthError("Saxo er ikke koblet til", status="REAUTH_REQUIRED")
            if current.environment != self.config.environment:
                raise SaxoAuthError("tokenet tilhører et annet Saxo-miljø", status="TOKEN_ENVIRONMENT_MISMATCH")
            if not force_refresh and current.access_is_valid():
                return current.access_token
            with self.store.refresh_guard():
                # Another Railway service may have refreshed while this process
                # waited for the advisory lock. Re-read before rotating again.
                current = self.store.load()
                if current is None:
                    raise SaxoAuthError("Saxo er ikke koblet til", status="REAUTH_REQUIRED")
                if not force_refresh and current.access_is_valid():
                    return current.access_token
                if not current.refresh_is_valid():
                    raise SaxoAuthError("refresh-token er utløpt", status="REAUTH_REQUIRED")
                return self._request_token(
                    {
                        "grant_type": "refresh_token",
                        "refresh_token": current.refresh_token,
                        "redirect_uri": self.config.redirect_uri,
                    }
                ).access_token

    def status(self) -> dict[str, Any]:
        current = self.store.load()
        if current is None:
            return {
                "connected": False,
                "environment": self.config.environment,
                "status": "NOT_CONNECTED",
            }
        now = _utc_now()
        access_seconds = int((current.access_expiry - now).total_seconds())
        refresh_expiry = current.refresh_expiry
        refresh_seconds = int((refresh_expiry - now).total_seconds()) if refresh_expiry else None
        return {
            "connected": current.refresh_is_valid(leeway_seconds=0),
            "environment": current.environment,
            "status": "CONNECTED" if current.refresh_is_valid(leeway_seconds=0) else "REAUTH_REQUIRED",
            "access_expires_at": current.access_expires_at,
            "refresh_expires_at": current.refresh_expires_at,
            "access_seconds_remaining": max(access_seconds, 0),
            "refresh_seconds_remaining": max(refresh_seconds, 0) if refresh_seconds is not None else None,
            "updated_at": current.updated_at,
        }

    def disconnect(self) -> None:
        with self._refresh_lock, self.store.refresh_guard():
            self.store.clear()

    def _request_token(self, form: dict[str, str]) -> SaxoTokenRecord:
        try:
            response = self.session.post(
                self.config.token_url,
                data=form,
                auth=(self.config.client_id, self.config.client_secret),
                headers={"Accept": "application/json", "User-Agent": "PriceGauger/1.0-alpha"},
                timeout=self.config.timeout,
            )
        except requests.Timeout as exc:
            raise SaxoAuthError("tidsavbrudd under tokenforespørsel", status="TIMEOUT") from exc
        except requests.ConnectionError as exc:
            raise SaxoAuthError("kunne ikke kontakte Saxo innlogging", status="CONNECTION_FAILED") from exc
        except requests.RequestException as exc:
            raise SaxoAuthError(type(exc).__name__, status="REQUEST_FAILED") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise SaxoAuthError("tokenresponsen var ikke gyldig JSON", status="INVALID_RESPONSE", status_code=response.status_code) from exc

        if not response.ok:
            message = "tokenforespørselen ble avvist"
            if isinstance(payload, dict):
                message = str(payload.get("error_description") or payload.get("error") or payload.get("message") or message)
            status = "REAUTH_REQUIRED" if response.status_code in {400, 401, 403} else "AUTH_FAILED"
            raise SaxoAuthError(message, status=status, status_code=response.status_code)
        if not isinstance(payload, dict):
            raise SaxoAuthError("tokenresponsen hadde ugyldig format", status="INVALID_RESPONSE")

        access_token = str(payload.get("access_token") or "").strip()
        refresh_token = str(payload.get("refresh_token") or "").strip()
        if not access_token or not refresh_token:
            raise SaxoAuthError("tokenresponsen manglet access- eller refresh-token", status="INVALID_RESPONSE")

        now = _utc_now()
        expires_in = max(int(payload.get("expires_in") or 0), 1)
        refresh_expires_in_raw = payload.get("refresh_token_expires_in")
        refresh_expires_at = None
        if refresh_expires_in_raw is not None:
            refresh_expires_at = (now + timedelta(seconds=max(int(refresh_expires_in_raw), 1))).isoformat()
        record = SaxoTokenRecord(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type=str(payload.get("token_type") or "Bearer"),
            access_expires_at=(now + timedelta(seconds=expires_in)).isoformat(),
            refresh_expires_at=refresh_expires_at,
            environment=self.config.environment,
            updated_at=now.isoformat(),
        )
        self.store.save(record)
        return record


def configured_oauth_client(secret_getter=None) -> SaxoOAuthClient | None:
    getter = secret_getter or _secret
    client_id = getter("SAXO_APP_KEY")
    client_secret = getter("SAXO_APP_SECRET")
    redirect_uri = getter("SAXO_REDIRECT_URI")
    if not client_id or not client_secret or not redirect_uri:
        return None
    environment = (getter("SAXO_ENVIRONMENT") or "sim").lower()
    auth_base_url = getter("SAXO_AUTH_BASE_URL")
    token_path = getter("SAXO_TOKEN_PATH")
    config = SaxoOAuthConfig(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        environment=environment,
        auth_base_url=auth_base_url,
        token_path=token_path,
    )
    from database import using_postgres

    store: SaxoTokenStoreProtocol
    if using_postgres():
        store = SaxoDatabaseTokenStore(environment)
    else:
        store = SaxoTokenStore(config.token_path)
    return SaxoOAuthClient(config, store=store)


def _secret(name: str) -> str:
    environment = os.getenv(name, "").strip()
    if environment:
        return environment
    try:
        import streamlit as st

        try:
            value = st.secrets.get(name, "")
        except Exception:
            return ""
        return str(value).strip() if value else ""
    except ImportError:
        return ""
