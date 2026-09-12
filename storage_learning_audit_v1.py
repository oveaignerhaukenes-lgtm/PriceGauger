from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from database import connect, using_postgres

AUDIT_VERSION = "storage-learning-audit-v1"
MIN_AUDIT_INTERVAL = timedelta(hours=20)


@dataclass(frozen=True, slots=True)
class StorageRelationStatV1:
    relation_name: str
    row_estimate: int
    table_bytes: int
    index_bytes: int
    total_bytes: int
    growth_bytes: int | None = None
    growth_per_day_bytes: float | None = None


@dataclass(frozen=True, slots=True)
class StorageAuditSummaryV1:
    captured_at: datetime
    database_bytes: int
    relations_total_bytes: int
    relation_count: int
    relations: tuple[StorageRelationStatV1, ...]


def _utc(value) -> datetime:
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _value(row, key: str, index: int = 0):
    return row[key] if isinstance(row, dict) else row[index]


def ensure_storage_audit_schema_v1() -> None:
    if not using_postgres():
        return
    with connect() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS pg_v2_storage_audit_runs (
                captured_at TIMESTAMPTZ PRIMARY KEY,
                audit_version TEXT NOT NULL,
                database_bytes BIGINT NOT NULL,
                relations_total_bytes BIGINT NOT NULL,
                relation_count INTEGER NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS pg_v2_storage_audit_relations (
                captured_at TIMESTAMPTZ NOT NULL REFERENCES pg_v2_storage_audit_runs(captured_at) ON DELETE CASCADE,
                relation_name TEXT NOT NULL,
                row_estimate BIGINT NOT NULL,
                table_bytes BIGINT NOT NULL,
                index_bytes BIGINT NOT NULL,
                total_bytes BIGINT NOT NULL,
                PRIMARY KEY (captured_at, relation_name)
            )
        """)
        db.execute("""
            CREATE INDEX IF NOT EXISTS pg_v2_storage_audit_relations_name_time_idx
            ON pg_v2_storage_audit_relations(relation_name, captured_at DESC)
        """)


def _latest_capture_v1() -> datetime | None:
    ensure_storage_audit_schema_v1()
    with connect() as db:
        row = db.execute("SELECT captured_at FROM pg_v2_storage_audit_runs ORDER BY captured_at DESC LIMIT 1").fetchone()
    return None if row is None else _utc(_value(row, "captured_at"))


def storage_audit_due_v1(*, now: datetime | None = None) -> bool:
    if not using_postgres():
        return False
    current = _utc(now or datetime.now(timezone.utc))
    latest = _latest_capture_v1()
    return latest is None or current - latest >= MIN_AUDIT_INTERVAL


def capture_storage_audit_v1(*, now: datetime | None = None, force: bool = False) -> StorageAuditSummaryV1 | None:
    if not using_postgres():
        return None
    current = _utc(now or datetime.now(timezone.utc)).replace(microsecond=0)
    ensure_storage_audit_schema_v1()
    if not force and not storage_audit_due_v1(now=current):
        return load_latest_storage_audit_v1()
    with connect() as db:
        size_row = db.execute("SELECT pg_database_size(current_database()) AS database_bytes").fetchone()
        database_bytes = int(_value(size_row, "database_bytes"))
        rows = db.execute("""
            SELECT c.relname AS relation_name,
                   GREATEST(c.reltuples::bigint, 0) AS row_estimate,
                   pg_relation_size(c.oid)::bigint AS table_bytes,
                   pg_indexes_size(c.oid)::bigint AS index_bytes,
                   pg_total_relation_size(c.oid)::bigint AS total_bytes
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname='public' AND c.relkind IN ('r','m')
              AND c.relname NOT LIKE 'pg_v2_storage_audit_%%'
            ORDER BY pg_total_relation_size(c.oid) DESC, c.relname
        """).fetchall()
        normalized = [dict(row) if isinstance(row, dict) else {
            "relation_name": row[0], "row_estimate": row[1], "table_bytes": row[2],
            "index_bytes": row[3], "total_bytes": row[4]
        } for row in rows]
        relation_bytes = sum(int(row["total_bytes"]) for row in normalized)
        db.execute("""
            INSERT INTO pg_v2_storage_audit_runs(captured_at,audit_version,database_bytes,relations_total_bytes,relation_count)
            VALUES (?,?,?,?,?) ON CONFLICT (captured_at) DO NOTHING
        """, (current, AUDIT_VERSION, database_bytes, relation_bytes, len(normalized)))
        for row in normalized:
            db.execute("""
                INSERT INTO pg_v2_storage_audit_relations(captured_at,relation_name,row_estimate,table_bytes,index_bytes,total_bytes)
                VALUES (?,?,?,?,?,?) ON CONFLICT (captured_at,relation_name) DO NOTHING
            """, (current, str(row["relation_name"]), int(row["row_estimate"]), int(row["table_bytes"]), int(row["index_bytes"]), int(row["total_bytes"])))
    return load_storage_audit_at_v1(current)


def load_storage_audit_at_v1(captured_at: datetime) -> StorageAuditSummaryV1 | None:
    stamp = _utc(captured_at)
    with connect() as db:
        run = db.execute("SELECT captured_at,database_bytes,relations_total_bytes,relation_count FROM pg_v2_storage_audit_runs WHERE captured_at=?", (stamp,)).fetchone()
        if run is None:
            return None
        rows = db.execute("""
            SELECT r.relation_name,r.row_estimate,r.table_bytes,r.index_bytes,r.total_bytes,
                   p.captured_at AS previous_at,p.total_bytes AS previous_total_bytes
            FROM pg_v2_storage_audit_relations r
            LEFT JOIN LATERAL (
                SELECT captured_at,total_bytes FROM pg_v2_storage_audit_relations p2
                WHERE p2.relation_name=r.relation_name AND p2.captured_at<r.captured_at
                ORDER BY captured_at DESC LIMIT 1
            ) p ON TRUE
            WHERE r.captured_at=? ORDER BY r.total_bytes DESC,r.relation_name
        """, (stamp,)).fetchall()
    stats = []
    for row in rows:
        v = dict(row) if isinstance(row, dict) else {"relation_name":row[0],"row_estimate":row[1],"table_bytes":row[2],"index_bytes":row[3],"total_bytes":row[4],"previous_at":row[5],"previous_total_bytes":row[6]}
        prev = v.get("previous_total_bytes")
        growth = None if prev is None else int(v["total_bytes"]) - int(prev)
        per_day = None
        if growth is not None and v.get("previous_at") is not None:
            days = max((stamp - _utc(v["previous_at"])).total_seconds()/86400.0, 1e-6)
            per_day = growth / days
        stats.append(StorageRelationStatV1(str(v["relation_name"]), int(v["row_estimate"]), int(v["table_bytes"]), int(v["index_bytes"]), int(v["total_bytes"]), growth, per_day))
    return StorageAuditSummaryV1(_utc(_value(run,"captured_at",0)), int(_value(run,"database_bytes",1)), int(_value(run,"relations_total_bytes",2)), int(_value(run,"relation_count",3)), tuple(stats))


def load_latest_storage_audit_v1() -> StorageAuditSummaryV1 | None:
    if not using_postgres():
        return None
    latest = _latest_capture_v1()
    return None if latest is None else load_storage_audit_at_v1(latest)
