from __future__ import annotations

import sqlite3

import database


def test_configured_postgres_overrides_explicit_legacy_sqlite_path(
    monkeypatch, tmp_path
):
    postgres_connection = object()
    monkeypatch.setattr(database, "using_postgres", lambda: True)
    monkeypatch.setattr(
        database.DatabaseConnection,
        "_open_postgres",
        lambda self: postgres_connection,
    )

    db = database.connect(tmp_path / "legacy.sqlite3")

    assert db.is_postgres is True
    assert db._connection is postgres_connection


def test_force_sqlite_keeps_isolated_test_database(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "using_postgres", lambda: True)

    path = tmp_path / "isolated.sqlite3"
    with database.connect(path, force_sqlite=True) as db:
        assert db.is_postgres is False
        db.execute("CREATE TABLE sample(value TEXT)")
        db.execute("INSERT INTO sample(value) VALUES (?)", ("ok",))

    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT value FROM sample").fetchone()[0] == "ok"


def test_railway_runtime_is_detected_from_service_environment(monkeypatch):
    for key in (
        "RAILWAY_ENVIRONMENT",
        "RAILWAY_ENVIRONMENT_ID",
        "RAILWAY_PROJECT_ID",
        "RAILWAY_SERVICE_ID",
    ):
        monkeypatch.delenv(key, raising=False)

    assert database._running_on_railway() is False

    monkeypatch.setenv("RAILWAY_SERVICE_ID", "service-test")
    assert database._running_on_railway() is True


def test_streamlit_runtime_prefers_app_secret_over_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://stale-environment")
    monkeypatch.setattr(database, "_running_in_streamlit", lambda: True)
    monkeypatch.setattr(
        database,
        "_streamlit_secret_value",
        lambda: ("postgresql://current-streamlit-secret", "st.secrets[DATABASE_URL]"),
    )

    assert database.database_url() == "postgresql://current-streamlit-secret"
    assert database.database_config_status()["source"] == "st.secrets[DATABASE_URL]"


def test_worker_runtime_prefers_environment_over_streamlit_secret(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://worker-environment")
    monkeypatch.setattr(database, "_running_in_streamlit", lambda: False)
    monkeypatch.setattr(
        database,
        "_streamlit_secret_value",
        lambda: ("postgresql://local-secret", "st.secrets[DATABASE_URL]"),
    )

    assert database.database_url() == "postgresql://worker-environment"
    assert database.database_config_status()["source"] == "environment:DATABASE_URL"


def test_postgres_read_is_retried_once_after_connection_loss(monkeypatch):
    class LostConnection:
        def execute(self, query, values):
            raise RuntimeError("connection lost")

        def close(self):
            return None

    class HealthyConnection:
        def execute(self, query, values):
            return (query, values)

        def close(self):
            return None

        def commit(self):
            return None

    db = object.__new__(database.DatabaseConnection)
    db.is_postgres = True
    db._connection = LostConnection()
    monkeypatch.setattr(db, "_open_postgres", lambda: HealthyConnection())

    result = db.execute("SELECT value FROM sample WHERE id=?", (7,))

    assert result == ("SELECT value FROM sample WHERE id=%s", (7,))


def test_postgres_write_is_not_retried_after_connection_loss(monkeypatch):
    class LostConnection:
        def execute(self, query, values):
            raise RuntimeError("connection lost")

    db = object.__new__(database.DatabaseConnection)
    db.is_postgres = True
    db._connection = LostConnection()
    monkeypatch.setattr(
        db,
        "_open_postgres",
        lambda: (_ for _ in ()).throw(AssertionError("write must not be retried")),
    )

    try:
        db.execute("INSERT INTO sample(value) VALUES (?)", ("x",))
    except RuntimeError as exc:
        assert str(exc) == "connection lost"
    else:
        raise AssertionError("expected original write failure")


def test_exit_preserves_original_error_when_rollback_connection_is_lost():
    class BrokenConnection:
        def rollback(self):
            raise RuntimeError("rollback connection lost")

        def close(self):
            raise RuntimeError("close connection lost")

    db = object.__new__(database.DatabaseConnection)
    db._connection = BrokenConnection()

    assert db.__exit__(RuntimeError, RuntimeError("original query error"), None) is False
