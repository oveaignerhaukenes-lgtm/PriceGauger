"""Append-only, account-scoped evidence ledger for future V3 AI interventions.

This module does not call models or Saxo and cannot change V3 execution.
Only actual evaluated AI decisions may be recorded, never inferred in hindsight.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from math import isfinite
from typing import Mapping

from database import connect

ACTIONS = frozenset({"HOLD", "REDUCE", "FLAT", "REVERSE"})
MODES = frozenset({"SHADOW", "LIVE"})


def _utc(value: datetime | str) -> datetime:
    value = value if isinstance(value, datetime) else datetime.fromisoformat(
        str(value).replace("Z", "+00:00")
    )
    if value.tzinfo is None:
        raise ValueError("AI evidence timestamps must have a timezone")
    return value.astimezone(timezone.utc)


def ensure_ai_decision_memory_v1(db_path="pricegauger.db") -> None:
    with connect(db_path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS pg_v3_ai_decision_memory_v1 (
            decision_id TEXT PRIMARY KEY,
            instance_id TEXT NOT NULL,
            account_id TEXT NOT NULL,
            instrument_id BIGINT NOT NULL,
            strategy_key TEXT NOT NULL,
            evaluated_at TIMESTAMPTZ NOT NULL,
            evidence_as_of TIMESTAMPTZ NOT NULL,
            evidence_hash TEXT NOT NULL,
            model_id TEXT NOT NULL,
            mode TEXT NOT NULL,
            action TEXT NOT NULL,
            confidence DOUBLE PRECISION NOT NULL,
            reason TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        db.execute("""CREATE INDEX IF NOT EXISTS pg_v3_ai_memory_instance_time_idx
            ON pg_v3_ai_decision_memory_v1(instance_id, evaluated_at DESC)""")


def record_ai_decision_v1(
    *, decision_id: str, instance_id: str, account_id: str,
    instrument_id: int, strategy_key: str, evaluated_at: datetime | str,
    evidence_as_of: datetime | str, model_id: str, mode: str, action: str,
    confidence: float, reason: str, evidence: Mapping,
    db_path="pricegauger.db",
) -> bool:
    """Persist a causal decision once; reject conflicting rewrites.

    The snapshot contains only evidence actually known at evaluation time.
    This method is an audit writer, NOT permission for order execution.
    """
    if not all(str(x).strip() for x in (
        decision_id, instance_id, account_id, strategy_key, model_id, reason
    )):
        raise ValueError("AI memory identity and reason are required")
    if int(instrument_id) <= 0:
        raise ValueError("instrument identity required")
    if action not in ACTIONS or mode not in MODES:
        raise ValueError("unsupported AI audit action/mode")
    if not isfinite(float(confidence)) or not 0 <= float(confidence) <= 1:
        raise ValueError("confidence must be finite in [0,1]")
    when, as_of = _utc(evaluated_at), _utc(evidence_as_of)
    if as_of > when:
        raise ValueError("AI memory must not use future evidence")
    payload = json.dumps(dict(evidence), sort_keys=True, separators=(",", ":"),
                         allow_nan=False, ensure_ascii=False)
    fingerprint = sha256(payload.encode("utf-8")).hexdigest()
    values = (
        str(decision_id), str(instance_id), str(account_id), int(instrument_id),
        str(strategy_key), when.isoformat(), as_of.isoformat(), fingerprint,
        str(model_id), str(mode), str(action), float(confidence),
        str(reason)[:3000], payload,
    )
    ensure_ai_decision_memory_v1(db_path)
    with connect(db_path) as db:
        existing = db.execute("""SELECT instance_id,account_id,instrument_id,
            strategy_key,evaluated_at,evidence_as_of,evidence_hash,model_id,
            mode,action,confidence,reason,evidence_json
            FROM pg_v3_ai_decision_memory_v1 WHERE decision_id=?""",
            (str(decision_id),)).fetchone()
        if existing is not None:
            row = dict(existing)
            expected = (
                "instance_id", "account_id", "instrument_id", "strategy_key",
                "evaluated_at", "evidence_as_of", "evidence_hash", "model_id",
                "mode", "action", "confidence", "reason", "evidence_json",
            )
            # PostgreSQL timestamps may be returned as datetime, not strings.
            seen = tuple(
                _utc(row[key]).isoformat() if key in {"evaluated_at", "evidence_as_of"}
                else int(row[key]) if key == "instrument_id"
                else float(row[key]) if key == "confidence"
                else row[key] for key in expected
            )
            if seen != values[1:]:
                raise ValueError("immutable AI decision ID conflicts with stored evidence")
            return False
        db.execute("""INSERT INTO pg_v3_ai_decision_memory_v1 (
            decision_id,instance_id,account_id,instrument_id,strategy_key,
            evaluated_at,evidence_as_of,evidence_hash,model_id,mode,action,
            confidence,reason,evidence_json
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(decision_id) DO NOTHING""", values)
    return True


def load_ai_decisions_v1(
    *, instance_id: str, account_id: str, instrument_id: int,
    limit: int = 30, db_path="pricegauger.db",
) -> tuple[dict, ...]:
    """Read ONLY decisions from the exact instance/account/instrument."""
    ensure_ai_decision_memory_v1(db_path)
    with connect(db_path) as db:
        rows = db.execute("""SELECT decision_id,strategy_key,evaluated_at,
            evidence_as_of,evidence_hash,model_id,mode,action,confidence,
            reason,evidence_json FROM pg_v3_ai_decision_memory_v1
            WHERE instance_id=? AND account_id=? AND instrument_id=?
            ORDER BY evaluated_at DESC, decision_id DESC LIMIT ?""",
            (str(instance_id), str(account_id), int(instrument_id),
             max(1, min(100, int(limit))))).fetchall()
    return tuple(dict(row) for row in rows)


__all__ = [
    "ACTIONS", "MODES", "ensure_ai_decision_memory_v1",
    "record_ai_decision_v1", "load_ai_decisions_v1",
]
