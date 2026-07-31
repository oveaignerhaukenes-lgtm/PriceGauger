from __future__ import annotations

import sqlite3

import database


def test_explicit_sqlite_path_ignores_configured_postgres(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "using_postgres", lambda: True)

    path = tmp_path / "isolated.sqlite3"
    with database.connect(path) as db:
        assert db.is_postgres is False
        db.execute("CREATE TABLE sample(value TEXT)")
        db.execute("INSERT INTO sample(value) VALUES (?)", ("ok",))

    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT value FROM sample").fetchone()[0] == "ok"


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
