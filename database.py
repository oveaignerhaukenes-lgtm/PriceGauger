from __future__ import annotations

import os
import sqlite3
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Iterable


_ENV_KEYS = ("DATABASE_URL", "DATABASE_PUBLIC_URL")
_SECRET_KEYS = ("DATABASE_URL", "DATABASE_PUBLIC_URL")
_DEFAULT_SQLITE_PATH = "pricegauger.db"


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


class DatabaseConnection(AbstractContextManager):
    """Minimal connection adapter shared by SQLite and PostgreSQL stores.

    Explicit non-default paths stay isolated SQLite databases for local tools and
    tests. In Railway production, a configured DATABASE_URL is authoritative even
    when a legacy mounted-volume path is supplied to the worker.
    """

    def __init__(self, sqlite_path: str | Path = _DEFAULT_SQLITE_PATH) -> None:
        self.sqlite_path = str(sqlite_path)
        explicit_sqlite = self.sqlite_path != _DEFAULT_SQLITE_PATH
        railway_postgres = _running_on_railway() and using_postgres()
        self.is_postgres = using_postgres() and (not explicit_sqlite or railway_postgres)
        if self.is_postgres:
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:  # pragma: no cover - deployment dependency guard
                raise RuntimeError(
                    "DATABASE_URL is configured, but psycopg is not installed"
                ) from exc
            self._connection = psycopg.connect(database_url(), row_factory=dict_row)
        else:
            connection = sqlite3.connect(self.sqlite_path)
            connection.row_factory = sqlite3.Row
            self._connection = connection

    def execute(self, sql: str, parameters: Iterable[Any] | None = None):
        query = _postgres_sql(sql) if self.is_postgres else sql
        return self._connection.execute(query, tuple(parameters or ()))

    def executescript(self, script: str) -> None:
        if not self.is_postgres:
            self._connection.executescript(script)
            return
        for statement in script.split(";"):
            statement = statement.strip()
            if statement:
                self._connection.execute(statement)

    def __enter__(self) -> "DatabaseConnection":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        try:
            if exc_type is None:
                self._connection.commit()
            else:
                self._connection.rollback()
        finally:
            self._connection.close()
        return False


def connect(sqlite_path: str | Path = _DEFAULT_SQLITE_PATH) -> DatabaseConnection:
    return DatabaseConnection(sqlite_path)
