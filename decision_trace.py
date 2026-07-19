from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from typing import Any, Iterable, Mapping
from uuid import uuid4

from event_dna import EventDNA, MarketProfile, SimilarEvent
from event_models import MarketEvent
from storage import connect


@dataclass(frozen=True, slots=True)
class DecisionTrace:
    trace_id: str
    created_at: str
    event_id: str
    asset: str
    event: dict[str, Any]
    event_dna: dict[str, Any]
    similar_events: list[dict[str, Any]]
    market_profile: dict[str, Any]
    assessment: dict[str, Any] | None
    strategy: dict[str, Any] | None
    outcome: dict[str, Any] | None = None

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


def _record(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "to_record"):
        return dict(value.to_record())
    if isinstance(value, Mapping):
        return dict(value)
    return dict(vars(value))


def build_decision_trace(
    *,
    event: MarketEvent,
    event_dna: EventDNA,
    similar_events: Iterable[SimilarEvent],
    market_profile: MarketProfile,
    assessment: Any | None = None,
    strategy: Any | None = None,
    outcome: Mapping[str, Any] | None = None,
    trace_id: str | None = None,
    created_at: str | None = None,
) -> DecisionTrace:
    timestamp = created_at or datetime.now(timezone.utc).isoformat()
    return DecisionTrace(
        trace_id=trace_id or str(uuid4()),
        created_at=timestamp,
        event_id=event.event_id,
        asset=market_profile.asset,
        event=event.to_record(),
        event_dna=event_dna.to_record(),
        similar_events=[item.to_record() for item in similar_events],
        market_profile=market_profile.to_record(),
        assessment=_record(assessment) or None,
        strategy=_record(strategy) or None,
        outcome=dict(outcome) if outcome is not None else None,
    )


def _ensure_table() -> None:
    with connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS decision_traces (
                trace_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                event_id TEXT NOT NULL,
                asset TEXT NOT NULL,
                event_json TEXT NOT NULL,
                event_dna_json TEXT NOT NULL,
                similar_events_json TEXT NOT NULL,
                market_profile_json TEXT NOT NULL,
                assessment_json TEXT,
                strategy_json TEXT,
                outcome_json TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_decision_traces_event_asset ON decision_traces(event_id, asset)"
        )
        connection.commit()


def save_decision_trace(trace: DecisionTrace) -> None:
    _ensure_table()
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO decision_traces (
                trace_id, created_at, event_id, asset, event_json, event_dna_json,
                similar_events_json, market_profile_json, assessment_json,
                strategy_json, outcome_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(trace_id) DO UPDATE SET
                created_at=excluded.created_at,
                event_id=excluded.event_id,
                asset=excluded.asset,
                event_json=excluded.event_json,
                event_dna_json=excluded.event_dna_json,
                similar_events_json=excluded.similar_events_json,
                market_profile_json=excluded.market_profile_json,
                assessment_json=excluded.assessment_json,
                strategy_json=excluded.strategy_json,
                outcome_json=excluded.outcome_json,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                trace.trace_id,
                trace.created_at,
                trace.event_id,
                trace.asset,
                json.dumps(trace.event, ensure_ascii=False, sort_keys=True),
                json.dumps(trace.event_dna, ensure_ascii=False, sort_keys=True),
                json.dumps(trace.similar_events, ensure_ascii=False, sort_keys=True),
                json.dumps(trace.market_profile, ensure_ascii=False, sort_keys=True),
                json.dumps(trace.assessment, ensure_ascii=False, sort_keys=True) if trace.assessment is not None else None,
                json.dumps(trace.strategy, ensure_ascii=False, sort_keys=True) if trace.strategy is not None else None,
                json.dumps(trace.outcome, ensure_ascii=False, sort_keys=True) if trace.outcome is not None else None,
            ),
        )
        connection.commit()


def update_decision_outcome(trace_id: str, outcome: Mapping[str, Any]) -> bool:
    _ensure_table()
    with connect() as connection:
        cursor = connection.execute(
            """
            UPDATE decision_traces
            SET outcome_json = ?, updated_at = CURRENT_TIMESTAMP
            WHERE trace_id = ?
            """,
            (json.dumps(dict(outcome), ensure_ascii=False, sort_keys=True), trace_id),
        )
        connection.commit()
        return cursor.rowcount > 0


def load_decision_trace(trace_id: str) -> DecisionTrace | None:
    _ensure_table()
    with connect() as connection:
        connection.row_factory = __import__("sqlite3").Row
        row = connection.execute(
            "SELECT * FROM decision_traces WHERE trace_id = ?",
            (trace_id,),
        ).fetchone()
    if row is None:
        return None
    return DecisionTrace(
        trace_id=row["trace_id"],
        created_at=row["created_at"],
        event_id=row["event_id"],
        asset=row["asset"],
        event=json.loads(row["event_json"]),
        event_dna=json.loads(row["event_dna_json"]),
        similar_events=json.loads(row["similar_events_json"]),
        market_profile=json.loads(row["market_profile_json"]),
        assessment=json.loads(row["assessment_json"]) if row["assessment_json"] else None,
        strategy=json.loads(row["strategy_json"]) if row["strategy_json"] else None,
        outcome=json.loads(row["outcome_json"]) if row["outcome_json"] else None,
    )
