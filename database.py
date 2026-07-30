from __future__ import annotations

import os
import sqlite3
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Iterable


_ENV_KEYS = ("DATABASE_URL", "DATABASE_PUBLIC_URL")
_SECRET_KEYS = ("DATABASE_URL", "DATABASE_PUBLIC_URL")
_DEFAULT_SQLITE_PATH = "pricegauger.db"


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


def database_config_status() -> dict[str, str | bool]:
    """Return non-secret diagnostics for the active database configuration."""
    for key in _ENV_KEYS:
        value = os.getenv(key, "").strip()
        if value:
            return {"configured": True, "source": f"environment:{key}", "backend": "PostgreSQL"}

    value, source = _streamlit_secret_value()
    if value:
        return {"configured": True, "source": source, "backend": "PostgreSQL"}
    return {"configured": False, "source": source, "backend": "SQLite"}


def database_url() -> str:
    """Return PostgreSQL URL from environment or Streamlit secrets."""
    for key in _ENV_KEYS:
        configured = os.getenv(key, "").strip()
        if configured:
            return configured

    value, _ = _streamlit_secret_value()
    return value


def using_postgres() -> bool:
    return bool(database_url())


def _postgres_sql(sql: str) -> str:
    """Translate the small qmark SQL subset used by PriceGauger to psycopg."""
    return sql.replace("?", "%s")


class DatabaseConnection(AbstractContextManager):
    """Minimal connection adapter shared by SQLite and PostgreSQL stores.

    The default database path follows DATABASE_URL when configured. Passing an
    explicit, non-default SQLite path is treated as an intentional local/test
    database and must never be redirected to the shared PostgreSQL database.
    """

    def __init__(self, sqlite_path: str | Path = _DEFAULT_SQLITE_PATH) -> None:
        self.sqlite_path = str(sqlite_path)
        explicit_sqlite = self.sqlite_path != _DEFAULT_SQLITE_PATH
        self.is_postgres = using_postgres() and not explicit_sqlite
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
