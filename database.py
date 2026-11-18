from __future__ import annotations

import os
import re
import hashlib
import sqlite3
import threading
import time
from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Iterable, Callable


_ENV_KEYS = ("DATABASE_URL", "DATABASE_PUBLIC_URL")
_SECRET_KEYS = ("DATABASE_URL", "DATABASE_PUBLIC_URL")
_DEFAULT_SQLITE_PATH = "pricegauger.db"
_DOLLAR_QUOTE_RE = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$")


def _running_in_streamlit() -> bool:
    """Return True only for an active Streamlit app runtime, not merely an installed package."""
    try:
        from streamlit.runtime import exists

        return bool(exists())
    except Exception:
        return False


def _running_on_railway() -> bool:
    """Return True inside a Railway deployment.

    Railway services may retain a legacy ``--db /data/...`` argument for a mounted
    SQLite volume. Once DATABASE_URL is configured, production state must still be
    written to PostgreSQL so the worker and Streamlit share one authoritative store.
    """
    return bool(
        os.getenv("RAILWAY_ENVIRONMENT", "").strip()
        or os.getenv("RAILWAY_ENVIRONMENT_ID", "").strip()
        or os.getenv("RAILWAY_PROJECT_ID", "").strip()
        or os.getenv("RAILWAY_SERVICE_ID", "").strip()
    )


def _streamlit_secret_value() -> tuple[str, str]:
    """Return a supported Streamlit secret value and a safe source label."""
    try:
        import streamlit as st

        for key in _SECRET_KEYS:
            value = st.secrets.get(key, "")
            if value:
                return str(value).strip(), f"st.secrets[{key}]"

        nested = st.secrets.get("database", {})
        if nested:
            for key in ("url", "URL", "database_url", "DATABASE_URL"):
                value = nested.get(key, "")
                if value:
                    return str(value).strip(), f"st.secrets[database.{key}]"
    except Exception:
        return "", "unavailable"
    return "", "missing"


def _environment_value() -> tuple[str, str]:
    for key in _ENV_KEYS:
        value = os.getenv(key, "").strip()
        if value:
            return value, f"environment:{key}"
    return "", "missing"


def _configured_database_value() -> tuple[str, str]:
    """Resolve the database URL without exposing it.

    Streamlit Cloud may expose an inherited environment variable in addition to
    app-specific secrets. Inside a running Streamlit app, the app's own secrets
    are authoritative. Workers and CLI processes continue to prefer environment
    variables.
    """
    if _running_in_streamlit():
        secret_value, secret_source = _streamlit_secret_value()
        if secret_value:
            return secret_value, secret_source
        return _environment_value()

    environment_value, environment_source = _environment_value()
    if environment_value:
        return environment_value, environment_source
    return _streamlit_secret_value()


def database_config_status() -> dict[str, str | bool]:
    """Return non-secret diagnostics for the active database configuration."""
    value, source = _configured_database_value()
    return {
        "configured": bool(value),
        "source": source,
        "backend": "PostgreSQL" if value else "SQLite",
        "runtime": "streamlit" if _running_in_streamlit() else "worker-or-cli",
    }


def database_url() -> str:
    """Return the resolved PostgreSQL URL from the authoritative runtime source."""
    value, _ = _configured_database_value()
    return value


def using_postgres() -> bool:
    return bool(database_url())


def _postgres_sql(sql: str) -> str:
    """Translate the small qmark SQL subset used by PriceGauger to psycopg."""
    return sql.replace("?", "%s")


def _is_read_only_sql(sql: str) -> bool:
    normalized = sql.lstrip().upper()
    return normalized.startswith(("SELECT ", "SHOW ", "WITH "))


def _split_postgres_script(script: str) -> tuple[str, ...]:
    """Split SQL statements without treating semicolons inside SQL syntax as delimiters.

    PriceGauger schema files contain ordinary PostgreSQL line/block comments and may
    contain quoted strings or dollar-quoted bodies. A raw ``str.split(';')`` corrupts
    a script whenever any of those regions contains a semicolon; production hit this
    when a descriptive ``--`` comment contained one.
    """
    statements: list[str] = []
    current: list[str] = []
    index = 0
    mode = "normal"
    block_depth = 0
    dollar_tag: str | None = None

    while index < len(script):
        if mode == "normal":
            if script.startswith("--", index):
                current.append("--")
                index += 2
                mode = "line_comment"
                continue
            if script.startswith("/*", index):
                current.append("/*")
                index += 2
                mode = "block_comment"
                block_depth = 1
                continue
            char = script[index]
            if char == "'":
                current.append(char)
                index += 1
                mode = "single_quote"
                continue
            if char == '"':
                current.append(char)
                index += 1
                mode = "double_quote"
                continue
            if char == "$":
                match = _DOLLAR_QUOTE_RE.match(script, index)
                if match is not None:
                    dollar_tag = match.group(0)
                    current.append(dollar_tag)
                    index = match.end()
                    mode = "dollar_quote"
                    continue
            if char == ";":
                statement = "".join(current).strip()
                if statement:
                    statements.append(statement)
                current = []
                index += 1
                continue
            current.append(char)
            index += 1
            continue

        if mode == "line_comment":
            char = script[index]
            current.append(char)
            index += 1
            if char == "\n":
                mode = "normal"
            continue

        if mode == "block_comment":
            if script.startswith("/*", index):
                current.append("/*")
                index += 2
                block_depth += 1
                continue
            if script.startswith("*/", index):
                current.append("*/")
                index += 2
                block_depth -= 1
                if block_depth == 0:
                    mode = "normal"
                continue
            current.append(script[index])
            index += 1
            continue

        if mode == "single_quote":
            char = script[index]
            current.append(char)
            index += 1
            if char == "'":
                if index < len(script) and script[index] == "'":
                    current.append("'")
                    index += 1
                else:
                    mode = "normal"
            continue

        if mode == "double_quote":
            char = script[index]
            current.append(char)
            index += 1
            if char == '"':
                if index < len(script) and script[index] == '"':
                    current.append('"')
                    index += 1
                else:
                    mode = "normal"
            continue

        if mode == "dollar_quote":
            if dollar_tag is not None and script.startswith(dollar_tag, index):
                current.append(dollar_tag)
                index += len(dollar_tag)
                dollar_tag = None
                mode = "normal"
                continue
            current.append(script[index])
            index += 1
            continue

    statement = "".join(current).strip()
    if statement:
        statements.append(statement)
    return tuple(statements)


# LIVE V3 account tasks may reuse PostgreSQL connections. This opt-in is
# scoped to the worker task's context, NOT to the worker's other jobs or the UI.
# Broker position/authorization state is never cached by the DB pool.
_V3_POSTGRES_POOL_ENABLED: ContextVar[bool] = ContextVar(
    "pricegauger_v3_postgres_pool_enabled", default=False
)
_V3_POSTGRES_POOL_LOCK = threading.Lock()
_V3_POSTGRES_POOL = None
_V3_POSTGRES_POOL_DSN = None
_V3_POSTGRES_POOL_MAX = 12
_V3_POSTGRES_POOL_WAIT_SECONDS = 3.0


@contextmanager
def v3_postgres_pool_scope():
    """Opt into bounded connections only while an independent V3 account runs."""
    token = _V3_POSTGRES_POOL_ENABLED.set(True)
    try:
        yield
    finally:
        _V3_POSTGRES_POOL_ENABLED.reset(token)


def _get_v3_postgres_pool():
    global _V3_POSTGRES_POOL, _V3_POSTGRES_POOL_DSN
    current_dsn = database_url()
    if not current_dsn:
        raise RuntimeError("V3 PostgreSQL pool requires DATABASE_URL")
    with _V3_POSTGRES_POOL_LOCK:
        if _V3_POSTGRES_POOL is not None:
            if _V3_POSTGRES_POOL_DSN != current_dsn:
                # Never reuse authenticated PostgreSQL sessions after a runtime
                # database change. Railway redeploys are required for rotation.
                raise RuntimeError("V3 PostgreSQL database URL changed; restart required")
            return _V3_POSTGRES_POOL
        try:
            from psycopg_pool import ConnectionPool
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("V3 PostgreSQL pool requires psycopg[pool]") from exc
        pool = ConnectionPool(
            conninfo=current_dsn,
            kwargs={"row_factory": dict_row, "connect_timeout": 10},
            min_size=0,
            max_size=_V3_POSTGRES_POOL_MAX,
            timeout=_V3_POSTGRES_POOL_WAIT_SECONDS,
            max_idle=300.0,
            check=ConnectionPool.check_connection,
            open=True,
        )
        _V3_POSTGRES_POOL = pool
        _V3_POSTGRES_POOL_DSN = current_dsn
        return pool


# PostgreSQL schema initialization is a deployment/bootstrap concern, not a
# per-tick operation. Guard only the Postgres case; SQLite tests and local
# workers preserve their existing automatic schema initialization behavior.
_POSTGRES_SCHEMA_LOCK = threading.Lock()
_POSTGRES_SCHEMA_READY: set[tuple[str, str]] = set()


def run_postgres_schema_once_v1(schema_key: str, initialize: Callable[[], None]) -> None:
    """Initialize one schema transactionally once per process/DB identity.

    Only mark readiness AFTER the initialization function commits. Waiting
    concurrent V3 tasks cannot observe a half-created schema. An error must be
    retried on the next call, not cached as success.
    """
    if not using_postgres():
        initialize()
        return
    identity = hashlib.sha256(database_url().encode("utf-8")).hexdigest()
    key = (str(schema_key), identity)
    with _POSTGRES_SCHEMA_LOCK:
        if key in _POSTGRES_SCHEMA_READY:
            return
        initialize()
        _POSTGRES_SCHEMA_READY.add(key)


class DatabaseConnection(AbstractContextManager):
    """Minimal connection adapter shared by SQLite and PostgreSQL stores.

    A configured DATABASE_URL is authoritative, including when callers retain a
    legacy --db path. Local tools and tests can explicitly request isolated
    SQLite storage with force_sqlite=True.
    """

    def __init__(
        self,
        sqlite_path: str | Path = _DEFAULT_SQLITE_PATH,
        *,
        force_sqlite: bool = False,
    ) -> None:
        self.sqlite_path = str(sqlite_path)
        # A configured PostgreSQL URL is the authoritative shared store in every
        # runtime. sqlite_path remains a legacy fallback argument; isolated
        # tools and tests must opt into SQLite explicitly.
        self.is_postgres = using_postgres() and not force_sqlite
        self._postgres_pool = None
        if self.is_postgres:
            if _V3_POSTGRES_POOL_ENABLED.get():
                started = time.perf_counter()
                pool = _get_v3_postgres_pool()
                self._connection = pool.getconn(timeout=_V3_POSTGRES_POOL_WAIT_SECONDS)
                self._postgres_pool = pool
                from v3_runtime_timing_v1 import record_v3_phase_v1
                record_v3_phase_v1("db_acquire", time.perf_counter() - started)
            else:
                self._connection = self._open_postgres()
        else:
            connection = sqlite3.connect(self.sqlite_path)
            connection.row_factory = sqlite3.Row
            self._connection = connection

    @staticmethod
    def _open_postgres():
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:  # pragma: no cover - deployment dependency guard
            raise RuntimeError(
                "DATABASE_URL is configured, but psycopg is not installed"
            ) from exc
        return psycopg.connect(
            database_url(),
            row_factory=dict_row,
            connect_timeout=10,
        )

    def execute(self, sql: str, parameters: Iterable[Any] | None = None):
        query = _postgres_sql(sql) if self.is_postgres else sql
        values = tuple(parameters or ())
        track = getattr(self, "is_postgres", False) and _V3_POSTGRES_POOL_ENABLED.get()
        started = time.perf_counter() if track else 0.0
        try:
            try:
                return self._connection.execute(query, values)
            except Exception:
                if not self.is_postgres or not _is_read_only_sql(sql):
                    raise
                # Only retry an idempotent read after a dropped connection.
                # Never repeat a broker-related or DB write mutation.
                old_connection = self._connection
                self._connection = None
                try:
                    old_connection.close()
                except Exception:
                    pass
                if getattr(self, "_postgres_pool", None) is not None:
                    self._postgres_pool.putconn(old_connection)
                    self._connection = self._postgres_pool.getconn(
                        timeout=_V3_POSTGRES_POOL_WAIT_SECONDS
                    )
                else:
                    self._connection = self._open_postgres()
                return self._connection.execute(query, values)
        finally:
            if track:
                from v3_runtime_timing_v1 import record_v3_phase_v1
                record_v3_phase_v1(
                    "db_read" if _is_read_only_sql(sql) else "db_write",
                    time.perf_counter() - started,
                )

    def executescript(self, script: str) -> None:
        if not self.is_postgres:
            self._connection.executescript(script)
            return
        for statement in _split_postgres_script(script):
            self._connection.execute(statement)

    def __enter__(self) -> "DatabaseConnection":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        connection = getattr(self, "_connection", None)
        if connection is None:
            return False
        track = getattr(self, "is_postgres", False) and _V3_POSTGRES_POOL_ENABLED.get()
        started = time.perf_counter() if track else 0.0
        try:
            if exc_type is None:
                connection.commit()
            else:
                try:
                    connection.rollback()
                except Exception:
                    # A dropped PostgreSQL connection cannot be rolled back. Preserve
                    # the original query exception instead of masking it here.
                    pass
        finally:
            try:
                pool = getattr(self, "_postgres_pool", None)
                if pool is not None:
                    self._connection = None
                    pool.putconn(connection)
                else:
                    connection.close()
            except Exception:
                # Preserve the original exception when connection cleanup fails.
                if exc_type is None:
                    raise
            finally:
                if track:
                    from v3_runtime_timing_v1 import record_v3_phase_v1
                    record_v3_phase_v1("db_finalize", time.perf_counter() - started)
        return False


def connect(
    sqlite_path: str | Path = _DEFAULT_SQLITE_PATH,
    *,
    force_sqlite: bool = False,
) -> DatabaseConnection:
    return DatabaseConnection(sqlite_path, force_sqlite=force_sqlite)
