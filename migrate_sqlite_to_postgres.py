from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path

import psycopg


TABLES: dict[str, tuple[str, ...]] = {
    "worker_messages": ("message_id", "status", "recorded_at"),
    "worker_metadata": ("key", "value"),
    "market_interpretations": (
        "event_id",
        "cluster_id",
        "published_at",
        "update_type",
        "payload_json",
    ),
    "market_state_snapshots": ("as_of", "payload_json"),
    "asset_recommendations": ("as_of", "asset", "payload_json"),
    "signal_outcomes": (
        "signal_id",
        "event_id",
        "asset",
        "created_at",
        "payload_json",
    ),
}

CONFLICT_KEYS: dict[str, tuple[str, ...]] = {
    "worker_messages": ("message_id",),
    "worker_metadata": ("key",),
    "market_interpretations": ("event_id",),
    "market_state_snapshots": ("as_of",),
    "asset_recommendations": ("as_of", "asset"),
    "signal_outcomes": ("signal_id",),
}


def sqlite_table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def migrate_table(
    source: sqlite3.Connection,
    target: psycopg.Connection,
    table: str,
    columns: tuple[str, ...],
) -> int:
    if not sqlite_table_exists(source, table):
        print(f"SKIP {table}: source table not found")
        return 0

    rows = source.execute(
        f"SELECT {', '.join(columns)} FROM {table}"  # table/columns are fixed constants
    ).fetchall()
    if not rows:
        print(f"OK   {table}: 0 rows")
        return 0

    placeholders = ", ".join(["%s"] * len(columns))
    conflict = ", ".join(CONFLICT_KEYS[table])
    updates = [column for column in columns if column not in CONFLICT_KEYS[table]]
    if updates:
        update_clause = ", ".join(f"{column}=EXCLUDED.{column}" for column in updates)
        conflict_clause = f"ON CONFLICT ({conflict}) DO UPDATE SET {update_clause}"
    else:
        conflict_clause = f"ON CONFLICT ({conflict}) DO NOTHING"

    statement = (
        f"INSERT INTO {table} ({', '.join(columns)}) "
        f"VALUES ({placeholders}) {conflict_clause}"
    )
    with target.cursor() as cursor:
        cursor.executemany(statement, [tuple(row) for row in rows])
    target.commit()
    print(f"OK   {table}: {len(rows)} rows upserted")
    return len(rows)


def migrate(sqlite_path: Path, database_url: str) -> int:
    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {sqlite_path}")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")

    migrated = 0
    source = sqlite3.connect(sqlite_path)
    source.row_factory = sqlite3.Row
    try:
        with psycopg.connect(database_url) as target:
            for table, columns in TABLES.items():
                migrated += migrate_table(source, target, table, columns)
    finally:
        source.close()
    return migrated


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="One-time idempotent migration from PriceGauger SQLite storage to PostgreSQL"
    )
    value.add_argument("--sqlite", default="/data/pricegauger.db")
    return value


def main() -> None:
    args = parser().parse_args()
    total = migrate(Path(args.sqlite), os.getenv("DATABASE_URL", "").strip())
    print(f"MIGRATION_OK rows={total}")


if __name__ == "__main__":
    main()
