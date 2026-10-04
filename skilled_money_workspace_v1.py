from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any
from uuid import uuid4

from database import connect


@dataclass(frozen=True, slots=True)
class SkilledMoneyWatchV1:
    watch_id: str
    canonical_market: str
    display_name: str
    provider: str
    provider_instrument_id: str
    asset_type: str | None
    symbol: str | None
    active: bool


@dataclass(frozen=True, slots=True)
class SkilledMoneyEventV1:
    event_id: str
    watch_id: str
    canonical_market: str
    display_name: str
    event_started_at: datetime
    event_ended_at: datetime | None
    move_summary: str
    question: str | None
    status: str
    created_at: datetime


def _row(row: Any, key: str, index: int) -> Any:
    if isinstance(row, dict):
        return row[key]
    try:
        return row[key]
    except (TypeError, IndexError):
        return row[index]


def _dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _json_placeholder(db) -> str:
    return "?::jsonb" if db.is_postgres else "?"


def ensure_skilled_money_schema_v1() -> None:
    with connect() as db:
        if db.is_postgres:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS pg_skilled_money_watchlist_v1 (
                    watch_id UUID PRIMARY KEY,
                    canonical_market TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    provider_instrument_id TEXT NOT NULL,
                    asset_type TEXT,
                    symbol TEXT,
                    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                    active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    UNIQUE(provider, provider_instrument_id)
                );
                CREATE TABLE IF NOT EXISTS pg_skilled_money_events_v1 (
                    event_id UUID PRIMARY KEY,
                    watch_id UUID NOT NULL REFERENCES pg_skilled_money_watchlist_v1(watch_id),
                    event_started_at TIMESTAMPTZ NOT NULL,
                    event_ended_at TIMESTAMPTZ,
                    move_summary TEXT NOT NULL,
                    question TEXT,
                    status TEXT NOT NULL DEFAULT 'OPEN',
                    technical_regime_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                    world_regime_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                    actor_state_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE INDEX IF NOT EXISTS pg_skilled_money_events_watch_time_idx
                    ON pg_skilled_money_events_v1(watch_id, event_started_at DESC);
                CREATE TABLE IF NOT EXISTS pg_skilled_money_revisions_v1 (
                    event_id UUID NOT NULL REFERENCES pg_skilled_money_events_v1(event_id) ON DELETE CASCADE,
                    revision INTEGER NOT NULL CHECK (revision > 0),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    summary TEXT NOT NULL,
                    evidence_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                    PRIMARY KEY(event_id, revision)
                );
                """
            )
        else:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS pg_skilled_money_watchlist_v1 (
                    watch_id TEXT PRIMARY KEY,
                    canonical_market TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    provider_instrument_id TEXT NOT NULL,
                    asset_type TEXT,
                    symbol TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(provider, provider_instrument_id)
                );
                CREATE TABLE IF NOT EXISTS pg_skilled_money_events_v1 (
                    event_id TEXT PRIMARY KEY,
                    watch_id TEXT NOT NULL REFERENCES pg_skilled_money_watchlist_v1(watch_id),
                    event_started_at TEXT NOT NULL,
                    event_ended_at TEXT,
                    move_summary TEXT NOT NULL,
                    question TEXT,
                    status TEXT NOT NULL DEFAULT 'OPEN',
                    technical_regime_json TEXT NOT NULL DEFAULT '{}',
                    world_regime_json TEXT NOT NULL DEFAULT '{}',
                    actor_state_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS pg_skilled_money_events_watch_time_idx
                    ON pg_skilled_money_events_v1(watch_id, event_started_at DESC);
                CREATE TABLE IF NOT EXISTS pg_skilled_money_revisions_v1 (
                    event_id TEXT NOT NULL REFERENCES pg_skilled_money_events_v1(event_id) ON DELETE CASCADE,
                    revision INTEGER NOT NULL CHECK (revision > 0),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    summary TEXT NOT NULL,
                    evidence_json TEXT NOT NULL DEFAULT '[]',
                    PRIMARY KEY(event_id, revision)
                );
                """
            )


def add_watch_v1(
    *,
    canonical_market: str,
    display_name: str,
    provider: str,
    provider_instrument_id: str | int,
    asset_type: str | None = None,
    symbol: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    ensure_skilled_money_schema_v1()
    market = canonical_market.strip()
    label = display_name.strip()
    provider_name = provider.strip().lower()
    provider_id = str(provider_instrument_id).strip()
    if not market or not label or not provider_name or not provider_id:
        raise ValueError("canonical market, display name, provider and provider instrument id are required")
    watch_id = str(uuid4())
    metadata_json = json.dumps(metadata or {}, sort_keys=True, separators=(",", ":"))
    with connect() as db:
        existing = db.execute(
            "SELECT watch_id FROM pg_skilled_money_watchlist_v1 WHERE provider = ? AND provider_instrument_id = ?",
            (provider_name, provider_id),
        ).fetchone()
        if existing is not None:
            existing_id = str(_row(existing, "watch_id", 0))
            db.execute(
                """
                UPDATE pg_skilled_money_watchlist_v1
                SET canonical_market = ?, display_name = ?, asset_type = ?, symbol = ?, active = TRUE
                WHERE watch_id = ?
                """,
                (market, label, asset_type, symbol, existing_id),
            )
            return existing_id
        placeholder = _json_placeholder(db)
        db.execute(
            f"""
            INSERT INTO pg_skilled_money_watchlist_v1
                (watch_id, canonical_market, display_name, provider, provider_instrument_id,
                 asset_type, symbol, metadata_json, active)
            VALUES (?, ?, ?, ?, ?, ?, ?, {placeholder}, TRUE)
            """,
            (watch_id, market, label, provider_name, provider_id, asset_type, symbol, metadata_json),
        )
    return watch_id


def list_watches_v1(*, active_only: bool = True) -> tuple[SkilledMoneyWatchV1, ...]:
    ensure_skilled_money_schema_v1()
    where = "WHERE active = TRUE" if active_only else ""
    with connect() as db:
        rows = db.execute(
            f"""
            SELECT watch_id, canonical_market, display_name, provider, provider_instrument_id,
                   asset_type, symbol, active
            FROM pg_skilled_money_watchlist_v1
            {where}
            ORDER BY display_name, provider, provider_instrument_id
            """
        ).fetchall()
    return tuple(
        SkilledMoneyWatchV1(
            watch_id=str(_row(row, "watch_id", 0)),
            canonical_market=str(_row(row, "canonical_market", 1)),
            display_name=str(_row(row, "display_name", 2)),
            provider=str(_row(row, "provider", 3)),
            provider_instrument_id=str(_row(row, "provider_instrument_id", 4)),
            asset_type=_row(row, "asset_type", 5),
            symbol=_row(row, "symbol", 6),
            active=bool(_row(row, "active", 7)),
        )
        for row in rows
    )


def set_watch_active_v1(watch_id: str, active: bool) -> None:
    ensure_skilled_money_schema_v1()
    with connect() as db:
        db.execute(
            "UPDATE pg_skilled_money_watchlist_v1 SET active = ? WHERE watch_id = ?",
            (bool(active), watch_id),
        )


def create_manual_event_v1(
    *,
    watch_id: str,
    event_started_at: datetime,
    event_ended_at: datetime | None,
    move_summary: str,
    question: str | None = None,
) -> str:
    ensure_skilled_money_schema_v1()
    summary = move_summary.strip()
    if not summary:
        raise ValueError("move summary is required")
    event_id = str(uuid4())
    started = event_started_at.astimezone(timezone.utc).isoformat()
    ended = event_ended_at.astimezone(timezone.utc).isoformat() if event_ended_at else None
    with connect() as db:
        watch = db.execute(
            "SELECT watch_id FROM pg_skilled_money_watchlist_v1 WHERE watch_id = ? AND active = TRUE",
            (watch_id,),
        ).fetchone()
        if watch is None:
            raise LookupError("watch is missing or inactive")
        empty_json = "{}"
        placeholder = _json_placeholder(db)
        db.execute(
            f"""
            INSERT INTO pg_skilled_money_events_v1
                (event_id, watch_id, event_started_at, event_ended_at, move_summary, question,
                 status, technical_regime_json, world_regime_json, actor_state_json)
            VALUES (?, ?, ?, ?, ?, ?, 'OPEN', {placeholder}, {placeholder}, {placeholder})
            """,
            (event_id, watch_id, started, ended, summary, (question or "").strip() or None,
             empty_json, empty_json, empty_json),
        )
    append_revision_v1(
        event_id=event_id,
        summary="Manuell hendelse opprettet. Analyse og senere evidens kan appendes uten å overskrive T0.",
        evidence=[],
    )
    return event_id


def append_revision_v1(*, event_id: str, summary: str, evidence: list[dict[str, Any]]) -> int:
    ensure_skilled_money_schema_v1()
    evidence_json = json.dumps(evidence, sort_keys=True, separators=(",", ":"), default=str)
    with connect() as db:
        row = db.execute(
            "SELECT COALESCE(MAX(revision), 0) FROM pg_skilled_money_revisions_v1 WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        revision = int(_row(row, "coalesce", 0)) + 1
        placeholder = _json_placeholder(db)
        db.execute(
            f"""
            INSERT INTO pg_skilled_money_revisions_v1(event_id, revision, summary, evidence_json)
            VALUES (?, ?, ?, {placeholder})
            """,
            (event_id, revision, summary.strip(), evidence_json),
        )
    return revision


def list_events_v1(*, limit: int = 50) -> tuple[SkilledMoneyEventV1, ...]:
    ensure_skilled_money_schema_v1()
    with connect() as db:
        rows = db.execute(
            """
            SELECT e.event_id, e.watch_id, w.canonical_market, w.display_name,
                   e.event_started_at, e.event_ended_at, e.move_summary, e.question,
                   e.status, e.created_at
            FROM pg_skilled_money_events_v1 e
            JOIN pg_skilled_money_watchlist_v1 w ON w.watch_id = e.watch_id
            ORDER BY e.event_started_at DESC, e.created_at DESC
            LIMIT ?
            """,
            (max(1, min(int(limit), 500)),),
        ).fetchall()
    return tuple(
        SkilledMoneyEventV1(
            event_id=str(_row(row, "event_id", 0)),
            watch_id=str(_row(row, "watch_id", 1)),
            canonical_market=str(_row(row, "canonical_market", 2)),
            display_name=str(_row(row, "display_name", 3)),
            event_started_at=_dt(_row(row, "event_started_at", 4)),
            event_ended_at=_dt(_row(row, "event_ended_at", 5)) if _row(row, "event_ended_at", 5) else None,
            move_summary=str(_row(row, "move_summary", 6)),
            question=_row(row, "question", 7),
            status=str(_row(row, "status", 8)),
            created_at=_dt(_row(row, "created_at", 9)),
        )
        for row in rows
    )


def list_revisions_v1(event_id: str) -> tuple[dict[str, Any], ...]:
    ensure_skilled_money_schema_v1()
    with connect() as db:
        rows = db.execute(
            """
            SELECT revision, created_at, summary, evidence_json
            FROM pg_skilled_money_revisions_v1
            WHERE event_id = ?
            ORDER BY revision ASC
            """,
            (event_id,),
        ).fetchall()
    revisions: list[dict[str, Any]] = []
    for row in rows:
        raw = _row(row, "evidence_json", 3)
        evidence = json.loads(raw) if isinstance(raw, str) else list(raw or [])
        revisions.append(
            {
                "revision": int(_row(row, "revision", 0)),
                "created_at": _dt(_row(row, "created_at", 1)),
                "summary": str(_row(row, "summary", 2)),
                "evidence": evidence,
            }
        )
    return tuple(revisions)
