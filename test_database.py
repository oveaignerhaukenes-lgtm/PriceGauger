from __future__ import annotations

from database import connect, database_url, using_postgres


def test_database_defaults_to_sqlite(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert database_url() == ""
    assert using_postgres() is False

    path = tmp_path / "adapter.db"
    with connect(path) as db:
        db.execute("CREATE TABLE sample (id TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.execute("INSERT INTO sample(id, value) VALUES (?, ?)", ("a", "first"))
        db.execute(
            """
            INSERT INTO sample(id, value) VALUES (?, ?)
            ON CONFLICT(id) DO UPDATE SET value=excluded.value
            """,
            ("a", "updated"),
        )

    with connect(path) as db:
        row = db.execute("SELECT value FROM sample WHERE id=?", ("a",)).fetchone()

    assert row["value"] == "updated"


def test_executescript_works_with_sqlite(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    path = tmp_path / "script.db"

    with connect(path) as db:
        db.executescript(
            """
            CREATE TABLE first_table (id TEXT PRIMARY KEY);
            CREATE TABLE second_table (id TEXT PRIMARY KEY);
            """
        )

    with connect(path) as db:
        names = {
            row["name"]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

    assert {"first_table", "second_table"}.issubset(names)
