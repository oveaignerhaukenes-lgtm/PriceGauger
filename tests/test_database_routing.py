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
