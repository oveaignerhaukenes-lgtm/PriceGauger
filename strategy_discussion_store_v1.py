from __future__ import annotations
from datetime import datetime, timezone
from database import connect

def ensure_strategy_discussion_schema_v1() -> None:
    with connect() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS pg_v2_strategy_discussion_messages (
                id TEXT PRIMARY KEY,
                strategy_key TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                hypothesis_version INTEGER,
                created_at TIMESTAMPTZ NOT NULL
            )
        """)

def append_strategy_message_v1(*, message_id: str, strategy_key: str, role: str,
                               content: str, hypothesis_version: int | None = None) -> None:
    ensure_strategy_discussion_schema_v1()
    with connect() as db:
        db.execute("""INSERT INTO pg_v2_strategy_discussion_messages
                      (id,strategy_key,role,content,hypothesis_version,created_at)
                      VALUES (?,?,?,?,?,?)""",
                   (message_id,strategy_key,role,content,hypothesis_version,datetime.now(timezone.utc)))

def load_strategy_messages_v1(strategy_key: str, *, limit: int = 40) -> tuple[dict[str, object], ...]:
    ensure_strategy_discussion_schema_v1()
    with connect() as db:
        rows=db.execute("""SELECT role,content,hypothesis_version,created_at
                           FROM pg_v2_strategy_discussion_messages
                           WHERE strategy_key=? ORDER BY created_at DESC LIMIT ?""",
                        (strategy_key,max(1,int(limit)))).fetchall()
    return tuple(dict(row) for row in reversed(rows))
