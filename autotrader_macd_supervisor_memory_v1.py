from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Sequence

import pandas as pd

from autotrader_macd_supervisor_replay_v1 import MacdSupervisorSwitchV1
from database import connect, using_postgres

MEMORY_VERSION_V1 = "macd-supervisor-memory-v1"
MODEL_VERSION_V1 = "macd-supervisor-v1"
OUTCOME_HORIZONS_V1 = (5, 15, 30, 60)

@dataclass(frozen=True, slots=True)
class SupervisorMemoryEpisodeV1:
    episode_id: int
    instrument_id: int
    action_at: datetime
    target: int
    score: float
    confidence: float
    context_score: float
    change_score: float
    explanation: str
    spreads: dict[int, float]
    slopes: dict[int, float]
    outcomes: dict[int, float]
    reflection_summary: str | None = None


def _utc(value) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def ensure_supervisor_memory_schema_v1() -> None:
    if not using_postgres():
        return
    with connect() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS pg_v2_macd_supervisor_memory (
                episode_id BIGSERIAL PRIMARY KEY,
                memory_version TEXT NOT NULL,
                model_version TEXT NOT NULL,
                instrument_id BIGINT NOT NULL,
                action_at TIMESTAMPTZ NOT NULL,
                price DOUBLE PRECISION NOT NULL,
                target SMALLINT NOT NULL CHECK (target IN (-1, 1)),
                score DOUBLE PRECISION NOT NULL,
                confidence DOUBLE PRECISION NOT NULL,
                context_score DOUBLE PRECISION NOT NULL,
                change_score DOUBLE PRECISION NOT NULL,
                explanation TEXT NOT NULL,
                spreads_json TEXT NOT NULL,
                slopes_json TEXT NOT NULL,
                outcome_5m DOUBLE PRECISION,
                outcome_15m DOUBLE PRECISION,
                outcome_30m DOUBLE PRECISION,
                outcome_60m DOUBLE PRECISION,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE(model_version, instrument_id, action_at)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS pg_v2_macd_supervisor_reflections (
                episode_id BIGINT PRIMARY KEY REFERENCES pg_v2_macd_supervisor_memory(episode_id) ON DELETE CASCADE,
                model TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                recommended_target SMALLINT NOT NULL CHECK (recommended_target IN (-1, 0, 1)),
                confidence DOUBLE PRECISION NOT NULL,
                summary TEXT NOT NULL,
                supporting_case TEXT NOT NULL,
                counter_case TEXT NOT NULL,
                invalidation TEXT NOT NULL,
                analogue_episode_ids_json TEXT NOT NULL DEFAULT '[]',
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS pg_v2_macd_supervisor_knowledge (
                knowledge_id BIGSERIAL PRIMARY KEY,
                model_version TEXT NOT NULL,
                scope TEXT NOT NULL,
                rule_key TEXT NOT NULL,
                statement TEXT NOT NULL,
                evidence_count INTEGER NOT NULL DEFAULT 0,
                expected_edge DOUBLE PRECISION,
                validation_status TEXT NOT NULL DEFAULT 'CANDIDATE',
                source_json TEXT NOT NULL DEFAULT '{}',
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE(model_version, scope, rule_key)
            )
        """)


def _dump(values: dict[int, float]) -> str:
    return json.dumps({str(k): float(v) for k, v in values.items()}, sort_keys=True)


def _load(raw: str) -> dict[int, float]:
    return {int(k): float(v) for k, v in json.loads(raw).items()}


def _forward_outcome(frame: pd.DataFrame, item: MacdSupervisorSwitchV1, minutes: int) -> float | None:
    at = pd.Timestamp(item.at)
    future = frame.loc[frame.index >= at + pd.Timedelta(minutes=minutes), "PRICE"]
    if future.empty or item.price <= 0:
        return None
    return float(item.target) * ((float(future.iloc[0]) / float(item.price)) - 1.0) * 100.0


def persist_supervisor_replay_memory_v1(*, instrument_id: int, replay: pd.DataFrame, switches: Sequence[MacdSupervisorSwitchV1]) -> int:
    if not using_postgres() or replay.empty:
        return 0
    ensure_supervisor_memory_schema_v1()
    saved = 0
    with connect() as db:
        for item in switches:
            outcomes = {m: _forward_outcome(replay, item, m) for m in OUTCOME_HORIZONS_V1}
            db.execute("""
                INSERT INTO pg_v2_macd_supervisor_memory(
                    memory_version, model_version, instrument_id, action_at, price, target,
                    score, confidence, context_score, change_score, explanation,
                    spreads_json, slopes_json, outcome_5m, outcome_15m, outcome_30m, outcome_60m, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, now())
                ON CONFLICT (model_version, instrument_id, action_at) DO UPDATE SET
                    score=EXCLUDED.score, confidence=EXCLUDED.confidence,
                    context_score=EXCLUDED.context_score, change_score=EXCLUDED.change_score,
                    explanation=EXCLUDED.explanation, spreads_json=EXCLUDED.spreads_json,
                    slopes_json=EXCLUDED.slopes_json,
                    outcome_5m=COALESCE(EXCLUDED.outcome_5m, pg_v2_macd_supervisor_memory.outcome_5m),
                    outcome_15m=COALESCE(EXCLUDED.outcome_15m, pg_v2_macd_supervisor_memory.outcome_15m),
                    outcome_30m=COALESCE(EXCLUDED.outcome_30m, pg_v2_macd_supervisor_memory.outcome_30m),
                    outcome_60m=COALESCE(EXCLUDED.outcome_60m, pg_v2_macd_supervisor_memory.outcome_60m), updated_at=now()
            """, (MEMORY_VERSION_V1, MODEL_VERSION_V1, int(instrument_id), _utc(item.at), float(item.price), int(item.target),
                  float(item.score), float(item.confidence), float(item.context_score), float(item.change_score), str(item.explanation),
                  _dump(item.spreads), _dump(item.slopes), outcomes[5], outcomes[15], outcomes[30], outcomes[60]))
            saved += 1
    return saved


def load_recent_supervisor_memories_v1(*, instrument_id: int, limit: int = 200) -> tuple[SupervisorMemoryEpisodeV1, ...]:
    if not using_postgres():
        return ()
    ensure_supervisor_memory_schema_v1()
    with connect() as db:
        rows = db.execute("""
            SELECT m.episode_id,m.instrument_id,m.action_at,m.target,m.score,m.confidence,
                   m.context_score,m.change_score,m.explanation,m.spreads_json,m.slopes_json,
                   m.outcome_5m,m.outcome_15m,m.outcome_30m,m.outcome_60m,r.summary
            FROM pg_v2_macd_supervisor_memory m
            LEFT JOIN pg_v2_macd_supervisor_reflections r ON r.episode_id=m.episode_id
            WHERE m.instrument_id=? AND m.model_version=? ORDER BY m.action_at DESC LIMIT ?
        """, (int(instrument_id), MODEL_VERSION_V1, max(1, min(5000, int(limit))))).fetchall()
    result = []
    for row in rows:
        v = dict(row)
        outcomes = {m: float(v[f"outcome_{m}m"]) for m in OUTCOME_HORIZONS_V1 if v.get(f"outcome_{m}m") is not None}
        result.append(SupervisorMemoryEpisodeV1(int(v["episode_id"]), int(v["instrument_id"]), _utc(v["action_at"]), int(v["target"]),
            float(v["score"]), float(v["confidence"]), float(v["context_score"]), float(v["change_score"]), str(v["explanation"]),
            _load(v["spreads_json"]), _load(v["slopes_json"]), outcomes, None if v.get("summary") is None else str(v["summary"])))
    return tuple(result)


def find_similar_supervisor_memories_v1(*, instrument_id: int, spreads: dict[int,float], limit: int = 8) -> tuple[SupervisorMemoryEpisodeV1, ...]:
    candidates = load_recent_supervisor_memories_v1(instrument_id=instrument_id, limit=500)
    keys = (1,2,5,10,15,30)
    qscale = max([abs(spreads.get(k,0.0)) for k in keys] + [1e-9])
    def distance(ep: SupervisorMemoryEpisodeV1) -> float:
        escale = max([abs(ep.spreads.get(k,0.0)) for k in keys] + [1e-9])
        return sum((ep.spreads.get(k,0.0)/escale - spreads.get(k,0.0)/qscale)**2 for k in keys)
    return tuple(sorted(candidates, key=distance)[:max(1,min(50,int(limit)))])


def aggregate_memory_edge_v1(episodes: Sequence[SupervisorMemoryEpisodeV1], *, horizon_minutes: int = 30) -> dict[str,float]:
    vals = [e.outcomes[horizon_minutes] for e in episodes if horizon_minutes in e.outcomes]
    if not vals:
        return {"count":0.0,"mean_pct":0.0,"win_rate_pct":0.0}
    return {"count":float(len(vals)),"mean_pct":float(sum(vals)/len(vals)),"win_rate_pct":float(sum(v>0 for v in vals)/len(vals)*100.0)}
