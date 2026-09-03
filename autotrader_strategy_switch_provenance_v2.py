from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from typing import Any
from uuid import uuid4

from autotrader_schema_v2 import ensure_autotrader_schema_v2
from autotrader_strategy_enrollment_v2 import StrategyEnrollmentV2
from database import connect


_SCHEMA_LOCK = Lock()
_SCHEMA_READY = False


@dataclass(frozen=True, slots=True)
class SettledFlatProvenanceV2:
    kind: str
    source_close_event_id: str | None


def _value(row: Any, key: str, index: int) -> Any:
    if isinstance(row, dict):
        return row[key]
    return row[index]


def ensure_strategy_switch_provenance_schema_v2() -> None:
    """Ensure durable audit state for strategy and user-confirmed FLAT authority."""
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return
        ensure_autotrader_schema_v2()
        with connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS pg_v2_autotrader_strategy_switch_events (
                    event_id UUID PRIMARY KEY,
                    from_pilot_key TEXT NOT NULL,
                    to_pilot_key TEXT NOT NULL,
                    from_strategy_key TEXT NOT NULL,
                    to_strategy_key TEXT NOT NULL,
                    observed_direction TEXT NOT NULL,
                    entry_mode TEXT NOT NULL,
                    live_open_was_armed BOOLEAN NOT NULL,
                    settled_flat_provenance BOOLEAN NOT NULL DEFAULT FALSE,
                    provenance_kind TEXT,
                    source_close_event_id UUID,
                    source_equity_at_switch DOUBLE PRECISION,
                    source_currency TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            db.execute(
                "ALTER TABLE pg_v2_autotrader_strategy_switch_events "
                "ADD COLUMN IF NOT EXISTS settled_flat_provenance BOOLEAN NOT NULL DEFAULT FALSE"
            )
            db.execute(
                "ALTER TABLE pg_v2_autotrader_strategy_switch_events "
                "ADD COLUMN IF NOT EXISTS provenance_kind TEXT"
            )
            db.execute(
                "ALTER TABLE pg_v2_autotrader_strategy_switch_events "
                "ADD COLUMN IF NOT EXISTS source_close_event_id UUID"
            )
            db.execute(
                "ALTER TABLE pg_v2_autotrader_strategy_switch_events "
                "ADD COLUMN IF NOT EXISTS source_equity_at_switch DOUBLE PRECISION"
            )
            db.execute(
                "ALTER TABLE pg_v2_autotrader_strategy_switch_events "
                "ADD COLUMN IF NOT EXISTS source_currency TEXT"
            )
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS pg_v2_autotrader_strategy_switch_target_time_idx
                ON pg_v2_autotrader_strategy_switch_events(to_pilot_key, created_at DESC)
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS pg_v2_autotrader_user_flat_authority (
                    authority_id UUID PRIMARY KEY,
                    pilot_key TEXT NOT NULL REFERENCES pg_v2_autotrader_strategy_enrollments(pilot_key),
                    source TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS pg_v2_autotrader_user_flat_authority_time_idx
                ON pg_v2_autotrader_user_flat_authority(pilot_key, created_at DESC)
                """
            )
        _SCHEMA_READY = True


def grant_user_confirmed_flat_authority_v2(*, pilot_key: str, source: str = "TRADINGDESK") -> str:
    """Persist one-shot OPEN authority after a caller has just confirmed Saxo FLAT.

    This is not a synthetic close and does not book P/L. It only records that the user
    explicitly requested fresh exposure while the exact external product was observed
    FLAT. The ordinary LIVE OPEN runtime still rechecks that Saxo remains FLAT before POST.
    """
    ensure_strategy_switch_provenance_schema_v2()
    authority_id = str(uuid4())
    with connect() as db:
        enrollment = db.execute(
            """
            SELECT 1 FROM pg_v2_autotrader_strategy_enrollments
            WHERE pilot_key = ? AND enabled = TRUE
            LIMIT 1
            """,
            (str(pilot_key),),
        ).fetchone()
        if enrollment is None:
            raise LookupError("active AutoManager pilot not found for user FLAT authority")
        db.execute(
            """
            INSERT INTO pg_v2_autotrader_user_flat_authority(
                authority_id, pilot_key, source
            ) VALUES (?, ?, ?)
            """,
            (authority_id, str(pilot_key), str(source)),
        )
    return authority_id


def require_source_settled_flat_provenance_v2(
    enrollment: StrategyEnrollmentV2,
) -> SettledFlatProvenanceV2:
    """Require a fully settled source ledger before creating a new strategy cohort.

    A source pilot that never controlled exposure may hand off from confirmed FLAT
    without a close event. Once an anchor position has existed, however, the latest
    cohort must contain an authoritative PG close whose realized P/L reconciliation
    is complete. Any unresolved close blocks the switch.
    """
    ensure_strategy_switch_provenance_schema_v2()
    with connect() as db:
        enrolled = db.execute(
            "SELECT enrolled_at FROM pg_v2_autotrader_strategy_enrollments WHERE pilot_key = ?",
            (enrollment.pilot_key,),
        ).fetchone()
        if enrolled is None:
            raise LookupError("source strategy enrollment disappeared")
        enrolled_at = _value(enrolled, "enrolled_at", 0)

        unresolved = db.execute(
            """
            SELECT close.event_id
            FROM pg_v2_autotrader_live_close_attempts AS close
            LEFT JOIN pg_v2_autotrader_equity_reconciliations AS rec
              ON rec.close_event_id = close.event_id
            WHERE close.account_id = ? AND close.uic = ? AND close.asset_type = ?
              AND close.created_at >= ?
              AND close.status IN ('SUBMITTING', 'ORDER_ACCEPTED', 'RECONCILED', 'UNCERTAIN')
              AND rec.close_event_id IS NULL
            ORDER BY close.created_at DESC
            LIMIT 1
            """,
            (
                enrollment.account_id,
                int(enrollment.uic),
                enrollment.asset_type,
                enrolled_at,
            ),
        ).fetchone()
        if unresolved is not None:
            raise ValueError(
                "strategy switch blocked: source pilot has an unresolved close/P&L reconciliation"
            )

        settled = db.execute(
            """
            SELECT close.event_id
            FROM pg_v2_autotrader_live_close_attempts AS close
            JOIN pg_v2_autotrader_equity_reconciliations AS rec
              ON rec.close_event_id = close.event_id
            WHERE close.account_id = ? AND close.uic = ? AND close.asset_type = ?
              AND close.created_at >= ? AND close.status = 'RECONCILED'
            ORDER BY close.created_at DESC
            LIMIT 1
            """,
            (
                enrollment.account_id,
                int(enrollment.uic),
                enrollment.asset_type,
                enrolled_at,
            ),
        ).fetchone()
        if settled is not None:
            return SettledFlatProvenanceV2(
                kind="SETTLED_PG_CLOSE",
                source_close_event_id=str(_value(settled, "event_id", 0)),
            )

    if enrollment.anchor_net_position_id.strip():
        raise ValueError(
            "strategy switch blocked: source pilot has exposure history without a settled PG close"
        )
    return SettledFlatProvenanceV2(kind="NO_SOURCE_EXPOSURE", source_close_event_id=None)


def has_unconsumed_settled_flat_handoff_v2(
    *,
    pilot_key: str,
    enrolled_at: datetime,
) -> bool:
    """Authorize one OPEN from either a settled FLAT handoff or explicit user FLAT.

    Both authorities are one-shot in effect. Once an OPEN reaches a state in which
    Saxo may already have accepted it, future automated re-entry again requires an
    ordinary settled PG close or a new explicit user target while confirmed FLAT.
    """
    ensure_strategy_switch_provenance_schema_v2()
    with connect() as db:
        handoff = db.execute(
            """
            SELECT event_id, created_at
            FROM pg_v2_autotrader_strategy_switch_events
            WHERE to_pilot_key = ?
              AND observed_direction = 'FLAT'
              AND settled_flat_provenance = TRUE
              AND created_at >= ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (str(pilot_key), enrolled_at),
        ).fetchone()
        user_flat = db.execute(
            """
            SELECT authority_id, created_at
            FROM pg_v2_autotrader_user_flat_authority
            WHERE pilot_key = ? AND created_at >= ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (str(pilot_key), enrolled_at),
        ).fetchone()

        candidates: list[tuple[Any, Any]] = []
        if handoff is not None:
            candidates.append((_value(handoff, "event_id", 0), _value(handoff, "created_at", 1)))
        if user_flat is not None:
            candidates.append((_value(user_flat, "authority_id", 0), _value(user_flat, "created_at", 1)))
        if not candidates:
            return False
        _, created_at = max(candidates, key=lambda item: item[1])

        consumed = db.execute(
            """
            SELECT 1
            FROM pg_v2_autotrader_execution_requests
            WHERE pilot_key = ? AND action = 'OPEN' AND created_at >= ?
              AND status IN ('SUBMITTING', 'ORDER_ACCEPTED', 'RECONCILED', 'UNCERTAIN')
            LIMIT 1
            """,
            (str(pilot_key), created_at),
        ).fetchone()
    return consumed is None


__all__ = [
    "SettledFlatProvenanceV2",
    "ensure_strategy_switch_provenance_schema_v2",
    "grant_user_confirmed_flat_authority_v2",
    "has_unconsumed_settled_flat_handoff_v2",
    "require_source_settled_flat_provenance_v2",
]
