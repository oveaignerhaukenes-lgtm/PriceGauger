from __future__ import annotations

import json
import logging
from typing import Any

import requests

from autotrader_macd_supervisor_memory_v1 import (
    aggregate_memory_edge_v1,
    ensure_supervisor_memory_schema_v1,
    find_similar_supervisor_memories_v1,
)
from config import openai_api_key, openai_market_model
from database import connect, using_postgres
from openai_market_provider import OPENAI_RESPONSES_URL, _response_output_text

LOGGER = logging.getLogger("pricegauger.autotrader.macd_supervisor_reflection_v1")
PROMPT_VERSION_V1 = "MACD-SUPERVISOR-REFLECTION-2026-09-12-v1"


def _schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "recommended_target": {"type": "integer", "enum": [-1, 0, 1]},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "summary": {"type": "string", "maxLength": 500},
            "supporting_case": {"type": "string", "maxLength": 800},
            "counter_case": {"type": "string", "maxLength": 800},
            "invalidation": {"type": "string", "maxLength": 500},
        },
        "required": ["recommended_target", "confidence", "summary", "supporting_case", "counter_case", "invalidation"],
    }


def _system_prompt() -> str:
    return (
        "You are the reflective layer of an experimental trading supervisor. "
        "The deterministic MACD supervisor is the stable baseline. Use its multi-timeframe state, "
        "its explanation, and outcomes from similar historical episodes to make a holistic judgment. "
        "Recommend LONG=1, HOLD/FLAT=0, or SHORT=-1. Do not invent market facts. "
        "Prefer continuity when evidence is weak; override the baseline only when the supplied evidence gives a coherent reason. "
        "Your output is analysis-only and has no execution authority."
    )


def _call(payload: dict[str, Any], *, api_key: str, model: str) -> dict[str, Any]:
    response = requests.post(
        OPENAI_RESPONSES_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "store": False,
            "input": [
                {"role": "system", "content": _system_prompt()},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)},
            ],
            "text": {"format": {"type": "json_schema", "name": "macd_supervisor_reflection", "schema": _schema(), "strict": True}},
        },
        timeout=45.0,
    )
    response.raise_for_status()
    parsed = json.loads(_response_output_text(response.json()))
    if not isinstance(parsed, dict):
        raise ValueError("Supervisor reflection must return an object")
    return parsed


def reflect_pending_supervisor_memories_v1(*, limit: int = 4) -> int:
    """Reflect on a few unreviewed episodes per worker cycle; never submits orders."""
    if not using_postgres():
        return 0
    key = openai_api_key().strip()
    if not key:
        return 0
    model = openai_market_model().strip() or "gpt-5-mini"
    ensure_supervisor_memory_schema_v1()
    with connect() as db:
        rows = db.execute("""
            SELECT m.episode_id,m.instrument_id,m.action_at,m.target,m.score,m.confidence,
                   m.context_score,m.change_score,m.explanation,m.spreads_json,m.slopes_json
            FROM pg_v2_macd_supervisor_memory m
            LEFT JOIN pg_v2_macd_supervisor_reflections r ON r.episode_id=m.episode_id
            WHERE r.episode_id IS NULL
            ORDER BY m.action_at DESC LIMIT ?
        """, (max(1, min(12, int(limit))),)).fetchall()
    saved = 0
    for row in rows:
        values = dict(row)
        spreads = {int(k): float(v) for k, v in json.loads(values["spreads_json"]).items()}
        slopes = {int(k): float(v) for k, v in json.loads(values["slopes_json"]).items()}
        analogues = find_similar_supervisor_memories_v1(
            instrument_id=int(values["instrument_id"]), spreads=spreads, limit=8
        )
        analogue_payload = []
        for episode in analogues:
            if int(episode.episode_id) == int(values["episode_id"]):
                continue
            analogue_payload.append({
                "episode_id": episode.episode_id,
                "target": episode.target,
                "score": episode.score,
                "context_score": episode.context_score,
                "change_score": episode.change_score,
                "outcomes_pct": episode.outcomes,
                "reflection_summary": episode.reflection_summary,
            })
        payload = {
            "episode_id": int(values["episode_id"]),
            "action_at": str(values["action_at"]),
            "baseline_target": int(values["target"]),
            "baseline_score": float(values["score"]),
            "baseline_confidence": float(values["confidence"]),
            "context_score": float(values["context_score"]),
            "change_score": float(values["change_score"]),
            "baseline_explanation": str(values["explanation"]),
            "macd_spreads": spreads,
            "macd_slopes": slopes,
            "similar_episodes": analogue_payload,
            "similar_30m_edge": aggregate_memory_edge_v1(tuple(a for a in analogues if a.episode_id != int(values["episode_id"])), horizon_minutes=30),
        }
        try:
            result = _call(payload, api_key=key, model=model)
        except Exception as exc:
            LOGGER.warning("MACD supervisor reflection failed episode=%s: %s", values["episode_id"], exc)
            continue
        with connect() as db:
            db.execute("""
                INSERT INTO pg_v2_macd_supervisor_reflections(
                    episode_id,model,prompt_version,recommended_target,confidence,summary,
                    supporting_case,counter_case,invalidation,analogue_episode_ids_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (episode_id) DO NOTHING
            """, (
                int(values["episode_id"]), model, PROMPT_VERSION_V1, int(result["recommended_target"]),
                float(result["confidence"]), str(result["summary"]), str(result["supporting_case"]),
                str(result["counter_case"]), str(result["invalidation"]),
                json.dumps([item["episode_id"] for item in analogue_payload]),
            ))
        saved += 1
    return saved


def load_supervisor_reflections_v1(*, instrument_id: int) -> dict[str, dict[str, Any]]:
    if not using_postgres():
        return {}
    ensure_supervisor_memory_schema_v1()
    with connect() as db:
        rows = db.execute("""
            SELECT m.action_at,r.recommended_target,r.confidence,r.summary,r.supporting_case,r.counter_case,r.invalidation
            FROM pg_v2_macd_supervisor_memory m
            JOIN pg_v2_macd_supervisor_reflections r ON r.episode_id=m.episode_id
            WHERE m.instrument_id=? ORDER BY m.action_at ASC
        """, (int(instrument_id),)).fetchall()
    return {
        str(dict(row)["action_at"]): {
            "target": int(dict(row)["recommended_target"]),
            "confidence": float(dict(row)["confidence"]),
            "summary": str(dict(row)["summary"]),
            "supporting_case": str(dict(row)["supporting_case"]),
            "counter_case": str(dict(row)["counter_case"]),
            "invalidation": str(dict(row)["invalidation"]),
        }
        for row in rows
    }
