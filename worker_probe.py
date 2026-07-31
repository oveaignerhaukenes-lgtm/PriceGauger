from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from database import connect


@dataclass(frozen=True, slots=True)
class WorkerProbe:
    component: str
    heartbeat_at: str
    database_identity: str
    cycle_status: str


def _database_identity(db) -> str:
    if not getattr(db, "is_postgres", False):
        return "sqlite-local"
    row = db.execute(
        """
        SELECT current_database() AS database_name,
               (SELECT oid FROM pg_database WHERE datname=current_database()) AS database_oid
        """
    ).fetchone()
    return f"{row['database_name']}:{row['database_oid']}"


def record_worker_probe(
    path: str | Path = "pricegauger.db",
    *,
    component: str = "state-runtime",
    cycle_status: str = "active",
) -> WorkerProbe:
    heartbeat_at = datetime.now(timezone.utc).isoformat()
    with connect(path) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS worker_runtime_probe (
                component TEXT PRIMARY KEY,
                heartbeat_at TEXT NOT NULL,
                database_identity TEXT NOT NULL,
                cycle_status TEXT NOT NULL
            );
            """
        )
        identity = _database_identity(db)
        db.execute(
            """
            INSERT INTO worker_runtime_probe(component, heartbeat_at, database_identity, cycle_status)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(component) DO UPDATE SET
                heartbeat_at=excluded.heartbeat_at,
                database_identity=excluded.database_identity,
                cycle_status=excluded.cycle_status
            """,
            (component, heartbeat_at, identity, cycle_status),
        )
    return WorkerProbe(component, heartbeat_at, identity, cycle_status)


def load_worker_probe(
    path: str | Path = "pricegauger.db",
    *,
    component: str = "state-runtime",
) -> WorkerProbe | None:
    try:
        with connect(path) as db:
            row = db.execute(
                """
                SELECT component, heartbeat_at, database_identity, cycle_status
                FROM worker_runtime_probe
                WHERE component=?
                """,
                (component,),
            ).fetchone()
    except Exception:
        return None
    if row is None:
        return None
    return WorkerProbe(
        component=str(row["component"]),
        heartbeat_at=str(row["heartbeat_at"]),
        database_identity=str(row["database_identity"]),
        cycle_status=str(row["cycle_status"]),
    )
