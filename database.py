from __future__ import annotations

import os
import sqlite3
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Iterable


def database_url() -> str:
    """Return DATABASE_URL from the environment or Streamlit secrets."""
    configured = os.getenv("DATABASE_URL", "").strip()
    if configured:
        return configured
    try:
        import streamlit as st

        value = st.secrets.get("DATABASE_URL", "")
        return str(value).strip() if value else ""
    except Exception:
        return ""


def using_postgres() -> bool:
    return bool(database_url())


def _postgres_sql(sql: str) -> str:
    """Translate the small qmark SQL subset used by PriceGauger to psycopg."""
    return sql.replace("?", "%s")


class DatabaseConnection(AbstractContextManager):
    """Minimal connection adapter shared by SQLite and PostgreSQL stores."""

    def __init__(self, sqlite_path: str | Path = "pricegauger.db") -> None:
        self.sqlite_path = str(sqlite_path)
        self.is_postgres = using_postgres()
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


def connect(sqlite_path: str | Path = "pricegauger.db") -> DatabaseConnection:
    return DatabaseConnection(sqlite_path)
