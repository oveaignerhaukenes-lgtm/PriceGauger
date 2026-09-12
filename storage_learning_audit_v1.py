from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from database import connect, using_postgres

AUDIT_VERSION = "storage-learning-audit-v1"
MIN_AUDIT_INTERVAL = timedelta(hours=20)


@dataclass(frozen=True, slots=True)
class StorageRelationStatV1:
    captured_at: datetime
    relation_name: str
    row_estimate: int
    table_bytes: int
    index_bytes: int
    total_bytes: int
    previous_total_bytes: int | None
    growth_bytes: int | None
    growth_per_day_bytes: float | None


@dataclass(frozen=True, slots=True)
class StorageAuditSummaryV1:
    captured_at: datetime
    database_bytes: int
    relations_total_bytes: int
    relation_count: int
    largest: tuple[StorageRelationStatV1, ...]


def _utc(value) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def ensure_storage_audit_schema_v1() -> None:
    if not using_postgres():
        return
    with connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pg_v2_storage_audit_runs (
                captured_at TIMESTAMPTZ PRIMARY KEY,
                audit_version TEXT NOT NULL,
                database_bytes BIGINT NOT NULL,
                relations_total_bytes BIGINT NOT NULL,
                relation_count INTEGER NOT NULL
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pg_v2_storage_audit_relations (
                captured_at TIMESTAMPTZ NOT NULL REFERENCES pg_v2_storage_audit_runs(captured_at) ON DELETE CASCADE,
                relation_name TEXT NOT NULL,
                row_estimate BIGINT NOT NULL,
                table_bytes BIGINT NOT NULL,
                index_bytes BIGINT NOT NULL,
                total_bytes BIGINT NOT NULL,
                PRIMARY KEY (captured_at, relation_name)
            )
            """
        )
        db.execute(
            """
            CREATE INDEX IF NOT EXISTS pg_v2_storage_audit_relations_name_time_idx
            ON pg_v2_storage_audit_relations(relation_name, captured_at DESC)
            """
        )


def _latest_capture_time_v1() -> datetime | None:
    ensure_storage_audit_schema_v1()
    with connect() as db:
        row = db.execute(
            "SELECT captured_at FROM pg_v2_storage_audit_runs ORDER BY captured_at DESC LIMIT 1"
        ).fetchone()
    if row is None:
        return None
    value = row["captured_at"] if isinstance(row, dict) else row[0]
    return _utc(value)


def storage_audit_due_v1(*, now: datetime | None = None) -> bool:
    if not using_postgres():
        return False
    current = _utc(now or datetime.now(timezone.utc))
    latest = _latest_capture_time_v1()
    return latest is None or current - latest >= MIN_AUDIT_INTERVAL


def _relation_rows_v1(db) -> Iterable:
    return db.execute(
        """
        SELECT
            c.relname AS relation_name,
            GREATEST(c.reltuples::bigint, 0) AS row_estimate,
            pg_relation_size(c.oid)::bigint AS table_bytes,
            pg_indexes_size(c.oid)::bigint AS index_bytes,
            pg_total_relation_size(c.oid)::bigint AS total_bytes
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind IN ('r','m')
          AND c.relname NOT LIKE 'pg_v2_storage_audit_%'
        ORDER BY pg_total_relation_size(c.oid) DESC, c.relname ASC
        """
    ).fetchall()


def capture_storage_audit_v1(*, now: datetime | None = None, force: bool = False) -> StorageAuditSummaryV1 | None:
    """Capture one compact PostgreSQL storage snapshot.

    The audit is deliberately non-destructive: it never deletes, vacuums, rewrites, or
    changes retention. It records only relation-level size/row estimates so we can learn
    which datasets are actually worth keeping before choosing a long-term retention model.
    """
    if not using_postgres():
        return None
    current = _utc(now or datetime.now(timezone.utc)).replace(microsecond=0)
    ensure_storage_audit_schema_v1()
    if not force and not storage_audit_due_v1(now=current):
        return load_latest_storage_audit_v1()

    with connect() as db:
        database_bytes = int(db.execute("SELECT pg_database_size(current_database())").fetchone()[0])
        rows = list(_relation_rows_v1(db))
        relation_values = []
        relations_total = 0
        for row in rows:
            values = dict(row) if isinstance(row, dict) else {
                "relation_name": row[0], "row_estimate": row[1], "table_bytes": row[2],
                "index_bytes": row[3], "total_bytes": row[4],
            }
            relations_total += int(values["total_bytes"])
            relation_values.append(values)

        db.execute(
            """
            INSERT INTO pg_v2_storage_audit_runs(
                captured_at, audit_version, database_bytes, relations_total_bytes, relation_count
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (captured_at) DO NOTHING
            """,
            (current, AUDIT_VERSION, database_bytes, relations_total, len(relation_values)),
        )
        for values in relation_values:
            db.execute(
                """
                INSERT INTO pg_v2_storage_audit_relations(
                    captured_at, relation_name, row_estimate, table_bytes, index_bytes, total_bytes
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (captured_at, relation_name) DO NOTHING
                """,
                (
                    current, str(values["relation_name"]), int(values["row_estimate"]),
                    int(values["table_bytes"]), int(values["index_bytes"]), int(values["total_bytes"]),
                ),
            )
    return load_storage_audit_at_v1(current)


def load_storage_audit_at_v1(captured_at: datetime) -> StorageAuditSummaryV1 | None:
    stamp = _utc(captured_at)
    with connect() as db:
        run = db.execute(
            """
            SELECT captured_at, database_bytes, relations_total_bytes, relation_count
            FROM pg_v2_storage_audit_runs WHERE captured_at = ?
            """,
            (stamp,),
        ).fetchone()
        if run is None:
            return None
        rows = db.execute(
            """
            SELECT r.relation_name, r.row_estimate, r.table_bytes, r.index_bytes, r.total_bytes,
                   p.captured_at AS previous_at, p.total_bytes AS previous_total_bytes
            FROM pg_v2_storage_audit_relations r
            LEFT JOIN LATERAL (
                SELECT p2.captured_at, p2.total_bytes
                FROM pg_v2_storage_audit_relations p2
                WHERE p2.relation_name = r.relation_name AND p2.captured_at < r.captured_at
                ORDER BY p2.captured_at DESC
                LIMIT 1
            ) p ON TRUE
            WHERE r.captured_at = ?
            ORDER BY r.total_bytes DESC, r.relation_name ASC
            """,
            (stamp,),
        ).fetchall()

    rv = dict(run) if isinstance(run, dict) else {
        "captured_at": run[0], "database_bytes": run[1],
        "relations_total_bytes": run[2], "relation_count": run[3],
    }
    stats: list[StorageRelationStatV1] = []
    for row in rows:
        values = dict(row) if isinstance(row, dict) else {
            "relation_name": row[0], "row_estimate": row[1], "table_bytes": row[2],
            "index_bytes": row[3], "total_bytes": row[4], "previous_at": row[5],
            "previous_total_bytes": row[6],
        }
        previous_total = values.get("previous_total_bytes")
        previous_at = values.get("previous_at")
        growth = None if previous_total is None else int(values["total_bytes"]) - int(previous_total)
        growth_per_day = None
        if growth is not None and previous_at is not None:
            elapsed_days = max((_utc(values["captured_at"]) - _utc(previous_at)).total_seconds() / 86400.0, 1e-6) if "captured_at" in values else max((stamp - _utc(previous_at)).total_seconds() / 86400.0, 1e-6)
            growth_per_day = float(growth) / elapsed_days
        stats.append(
            StorageRelationStatV1(
                captured_at=stamp,
                relation_name=str(values["relation_name"]),
                row_estimate=int(values["row_estimate"]),
                table_bytes=int(values["table_bytes"]),
                index_bytes=int(values["index_bytes"]),
                total_bytes=int(values["total_bytes"]),
                previous_total_bytes=None if previous_total is None else int(previous_total),
                growth_bytes=growth,
                growth_per_day_bytes=growth_per_day,
            )
        )
    return StorageAuditSummaryV1(
        captured_at=_utc(rv["captured_at"]),
        database_bytes=int(rv["database_bytes"]),
        relations_total_bytes=int(rv["relations_total_bytes"]),
        relation_count=int(rv["relation_count"]),
        largest=tuple(stats),
    )


def load_latest_storage_audit_v1() -> StorageAuditSummaryV1 | None:
    if not using_postgres():
        return None
    latest = _latest_capture_time_v1()
    return None if latest is None else load_storage_audit_at_v1(latest)


__all__ = [
    "AUDIT_VERSION",
    "StorageAuditSummaryV1",
    "StorageRelationStatV1",
    "capture_storage_audit_v1",
    "ensure_storage_audit_schema_v1",
    "load_latest_storage_audit_v1",
    "storage_audit_due_v1",
]
