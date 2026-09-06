from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from typing import Any

from database import connect
from instrument_registry_v2 import list_subscribed_sources_v2, resolve_instrument_source_v2


LOGGER = logging.getLogger("pricegauger.futures_rollover_schema_v1")


def _ensure_schema_v1() -> None:
    with connect() as db:
        json_default = "'{}'::jsonb" if db.is_postgres else "'{}'"
        db.execute(
            f"""
            CREATE TABLE IF NOT EXISTS pg_v2_instrument_rollovers (
                rollover_id {'BIGSERIAL' if db.is_postgres else 'INTEGER'} PRIMARY KEY,
                market_id BIGINT NOT NULL REFERENCES pg_v2_markets(market_id),
                old_instrument_id BIGINT NOT NULL REFERENCES pg_v2_instruments(instrument_id),
                new_instrument_id BIGINT NOT NULL REFERENCES pg_v2_instruments(instrument_id),
                provider TEXT NOT NULL,
                old_provider_instrument_id TEXT NOT NULL,
                new_provider_instrument_id TEXT NOT NULL,
                old_symbol TEXT,
                new_symbol TEXT,
                occurred_at {'TIMESTAMPTZ' if db.is_postgres else 'TEXT'} NOT NULL,
                reason TEXT NOT NULL,
                metadata_json {'JSONB' if db.is_postgres else 'TEXT'} NOT NULL DEFAULT {json_default},
                created_at {'TIMESTAMPTZ' if db.is_postgres else 'TEXT'} NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(provider, old_provider_instrument_id, new_provider_instrument_id)
            )
            """
        )
        db.execute(
            """
            CREATE INDEX IF NOT EXISTS pg_v2_instrument_rollovers_market_time_idx
            ON pg_v2_instrument_rollovers(market_id, occurred_at DESC)
            """
        )
        db.execute(
            """
            CREATE INDEX IF NOT EXISTS pg_v2_instrument_rollovers_new_instrument_idx
            ON pg_v2_instrument_rollovers(new_instrument_id, occurred_at DESC)
            """
        )


def _source_created_at_v1(*, provider: str, provider_instrument_id: str) -> datetime:
    with connect() as db:
        row = db.execute(
            """
            SELECT created_at
            FROM pg_v2_instrument_sources
            WHERE provider = ? AND provider_instrument_id = ?
            ORDER BY instrument_source_id DESC
            LIMIT 1
            """,
            (str(provider), str(provider_instrument_id)),
        ).fetchone()
    raw = row["created_at"] if isinstance(row, dict) else (row[0] if row else None)
    if isinstance(raw, datetime):
        stamp = raw
    else:
        try:
            stamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except Exception:
            stamp = datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def _recover_partial_rollovers_v1() -> int:
    """Recover audit rows if a prior collection switch completed before audit persistence.

    New contract sources created by the rollover resolver carry `rollover_from_uic` in
    metadata. That marker is presentation/audit-only and does not grant execution
    authority. Recovery is idempotent through the rollover table's unique identity.
    """

    recovered = 0
    for current in list_subscribed_sources_v2(provider="saxo"):
        metadata = dict(current.metadata or {})
        old_uic = str(metadata.get("rollover_from_uic") or "").strip()
        if not old_uic:
            continue
        try:
            old = resolve_instrument_source_v2(
                provider="saxo",
                provider_instrument_id=old_uic,
                require_subscription=False,
            )
        except LookupError:
            LOGGER.warning(
                "Cannot recover rollover audit market=%s new_uic=%s old_uic=%s: old source missing",
                current.market_name,
                current.provider_instrument_id,
                old_uic,
            )
            continue
        if int(old.market_id) != int(current.market_id):
            LOGGER.warning(
                "Cannot recover rollover audit new_uic=%s old_uic=%s: canonical market mismatch",
                current.provider_instrument_id,
                old_uic,
            )
            continue
        occurred_at = _source_created_at_v1(
            provider="saxo",
            provider_instrument_id=str(current.provider_instrument_id),
        )
        payload = json.dumps(
            {
                "recovered_audit": True,
                "old_expiry": (old.metadata or {}).get("expiry"),
                "new_expiry": metadata.get("expiry"),
                "selection": "RECOVERED_FROM_ROLLOVER_SOURCE_METADATA",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        with connect() as db:
            placeholder = "?::jsonb" if db.is_postgres else "?"
            cursor = db.execute(
                f"""
                INSERT INTO pg_v2_instrument_rollovers
                    (market_id, old_instrument_id, new_instrument_id, provider,
                     old_provider_instrument_id, new_provider_instrument_id,
                     old_symbol, new_symbol, occurred_at, reason, metadata_json)
                VALUES (?, ?, ?, 'saxo', ?, ?, ?, ?, ?, ?, {placeholder})
                ON CONFLICT (provider, old_provider_instrument_id, new_provider_instrument_id)
                DO NOTHING
                """,
                (
                    int(current.market_id),
                    int(old.instrument_id),
                    int(current.instrument_id),
                    old_uic,
                    str(current.provider_instrument_id),
                    str(old.symbol or "") or None,
                    str(current.symbol or "") or None,
                    occurred_at,
                    str(metadata.get("rollover_reason") or "RECOVERED_PARTIAL_ROLL"),
                    payload,
                ),
            )
            rowcount = int(getattr(cursor, "rowcount", 0) or 0)
        if rowcount > 0:
            recovered += 1
            LOGGER.warning(
                "Recovered futures rollover audit market=%s old_uic=%s new_uic=%s",
                current.market_name,
                old_uic,
                current.provider_instrument_id,
            )
    return recovered


def ensure_futures_rollover_audit_ready_v1() -> int:
    """Ensure the bounded rollover schema exists and reconcile any partial prior roll."""

    _ensure_schema_v1()
    return _recover_partial_rollovers_v1()


__all__ = ["ensure_futures_rollover_audit_ready_v1"]
