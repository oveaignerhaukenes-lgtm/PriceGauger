from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import logging
import time
from typing import Any, Mapping

import requests

from autotrader_shadow_benchmark_v2 import (
    STATE_FLAT,
    STATE_LONG,
    STATE_SHORT,
    ShadowBenchmarkSeriesV2,
    ShadowEquityPointV2,
    apply_shadow_return_v2,
)
from autotrader_strategy_enrollment_v2 import EXECUTION_MODE_LIVE, load_active_strategy_enrollments_v2
from canonical_market_bars_v2 import CanonicalMarketBarStoreV2
from config import openai_api_key, openai_market_model
from database import connect, using_postgres
from market_chat import build_market_chat_context
from openai_market_provider import OPENAI_RESPONSES_URL, _response_output_text


LOGGER = logging.getLogger("pricegauger.autotrader.ai_baseline_v1")
STRATEGY_KEY = "gpt-5-mini-ai-baseline-v1"
PROMPT_VERSION = "AI-BASELINE-2026-09-03-v1"
DECISION_INTERVAL_MINUTES = 5
MAX_DECISION_AGE = timedelta(minutes=12)


@dataclass(frozen=True, slots=True)
class AIBaselineDecisionV1:
    instrument_id: int
    market_name: str
    action_at: datetime
    price: float
    target_direction: str
    confidence: float
    horizon_minutes: int
    summary: str
    technical_case: str
    news_case: str
    invalidation: str
    model: str
    context_hash: str


def _utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _decision_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "target_direction": {"type": "string", "enum": [STATE_LONG, STATE_SHORT, STATE_FLAT]},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "horizon_minutes": {"type": "integer", "minimum": 1, "maximum": 240},
            "summary": {"type": "string", "maxLength": 400},
            "technical_case": {"type": "string", "maxLength": 700},
            "news_case": {"type": "string", "maxLength": 700},
            "invalidation": {"type": "string", "maxLength": 500},
        },
        "required": [
            "target_direction",
            "confidence",
            "horizon_minutes",
            "summary",
            "technical_case",
            "news_case",
            "invalidation",
        ],
    }


def _system_prompt() -> str:
    return (
        "You are an experimental trading-policy baseline inside PriceGauger. "
        "You receive only persisted market evidence. Choose exactly one target exposure: LONG, SHORT, or FLAT. "
        "Optimize the risk-adjusted result over roughly the next 5-60 minutes, while using slower context when relevant. "
        "Technicals, direct price behavior, regime information and supplied news/context may all matter. "
        "Do not assume facts newer than the supplied snapshot. Do not invent headlines or prices. "
        "FLAT is a valid active decision when evidence is conflicting. "
        "You have no authority over position size, leverage, order type, account, or execution; those are handled elsewhere. "
        "Treat the current AI state as context, not as an instruction. Return only the required structured result."
    )


def ensure_ai_baseline_schema_v1() -> None:
    with connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pg_v2_autotrader_ai_baseline_samples (
                strategy_key TEXT NOT NULL,
                instrument_id BIGINT NOT NULL,
                market_name TEXT NOT NULL,
                action_at TIMESTAMPTZ NOT NULL,
                price DOUBLE PRECISION NOT NULL,
                model TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                target_direction TEXT NOT NULL CHECK (target_direction IN ('FLAT','LONG','SHORT')),
                confidence DOUBLE PRECISION NOT NULL,
                horizon_minutes INTEGER NOT NULL,
                summary TEXT NOT NULL,
                technical_case TEXT NOT NULL,
                news_case TEXT NOT NULL,
                invalidation TEXT NOT NULL,
                context_hash TEXT NOT NULL,
                context_json TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY(strategy_key, instrument_id, action_at)
            )
            """
        )
        db.execute(
            """
            CREATE INDEX IF NOT EXISTS pg_v2_autotrader_ai_baseline_latest_idx
            ON pg_v2_autotrader_ai_baseline_samples(instrument_id, action_at DESC)
            """
        )


def _latest_cocktail_clock(instrument_id: int) -> tuple[str, datetime, float] | None:
    with connect() as db:
        row = db.execute(
            """
            SELECT market_name, action_at, price
            FROM pg_v2_autotrader_cocktail_mode_1_samples
            WHERE instrument_id = ?
            ORDER BY action_at DESC
            LIMIT 1
            """,
            (int(instrument_id),),
        ).fetchone()
    if row is None:
        return None
    values = dict(row) if isinstance(row, dict) else {
        "market_name": row[0], "action_at": row[1], "price": row[2]
    }
    return str(values["market_name"]), _utc(values["action_at"]), float(values["price"])


def _decision_exists(instrument_id: int, action_at: datetime) -> bool:
    with connect() as db:
        row = db.execute(
            """
            SELECT 1 FROM pg_v2_autotrader_ai_baseline_samples
            WHERE strategy_key = ? AND instrument_id = ? AND action_at = ?
            LIMIT 1
            """,
            (STRATEGY_KEY, int(instrument_id), _utc(action_at)),
        ).fetchone()
    return row is not None


def load_latest_ai_decision_v1(instrument_id: int) -> AIBaselineDecisionV1 | None:
    ensure_ai_baseline_schema_v1()
    with connect() as db:
        row = db.execute(
            """
            SELECT instrument_id, market_name, action_at, price, target_direction,
                   confidence, horizon_minutes, summary, technical_case, news_case,
                   invalidation, model, context_hash
            FROM pg_v2_autotrader_ai_baseline_samples
            WHERE strategy_key = ? AND instrument_id = ?
            ORDER BY action_at DESC
            LIMIT 1
            """,
            (STRATEGY_KEY, int(instrument_id)),
        ).fetchone()
    if row is None:
        return None
    values = dict(row) if isinstance(row, dict) else {
        "instrument_id": row[0], "market_name": row[1], "action_at": row[2], "price": row[3],
        "target_direction": row[4], "confidence": row[5], "horizon_minutes": row[6],
        "summary": row[7], "technical_case": row[8], "news_case": row[9],
        "invalidation": row[10], "model": row[11], "context_hash": row[12],
    }
    return AIBaselineDecisionV1(
        instrument_id=int(values["instrument_id"]),
        market_name=str(values["market_name"]),
        action_at=_utc(values["action_at"]),
        price=float(values["price"]),
        target_direction=str(values["target_direction"]),
        confidence=float(values["confidence"]),
        horizon_minutes=int(values["horizon_minutes"]),
        summary=str(values["summary"]),
        technical_case=str(values["technical_case"]),
        news_case=str(values["news_case"]),
        invalidation=str(values["invalidation"]),
        model=str(values["model"]),
        context_hash=str(values["context_hash"]),
    )


def ai_decision_is_fresh_v1(decision: AIBaselineDecisionV1, *, now: datetime | None = None) -> bool:
    current = _utc(now or datetime.now(timezone.utc))
    age = current - decision.action_at
    return timedelta(0) <= age <= MAX_DECISION_AGE


def _compact_context(market_name: str, *, db_path: str, action_at: datetime, current_state: str) -> dict[str, Any]:
    full = build_market_chat_context(market_name, db_path=db_path, now=action_at)
    history = list(full.get("canonical_price_history") or [])[-120:]
    posts = list(full.get("recent_telegram_posts_for_market") or [])[:8]
    forecasts = list(full.get("recent_forecasts") or [])[:6]
    return {
        "context_version": "ai-baseline-context-v1",
        "action_at": action_at.isoformat(),
        "market": market_name,
        "current_ai_state": current_state,
        "technical_market_state": full.get("technical_market_state"),
        "decision_engine_components": full.get("decision_engine_components"),
        "news_context": full.get("news_context"),
        "latest_market_mover": full.get("latest_market_mover"),
        "telegram_flow_for_market": full.get("telegram_flow_for_market"),
        "recent_market_posts": posts,
        "recent_forecasts": forecasts,
        "learning_summary": full.get("learning_summary"),
        "canonical_price_history": history,
    }


def _call_model(*, context: Mapping[str, Any], api_key: str, model: str, timeout_seconds: float = 45.0) -> dict[str, Any]:
    response = requests.post(
        OPENAI_RESPONSES_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "store": False,
            "input": [
                {"role": "system", "content": _system_prompt()},
                {"role": "user", "content": json.dumps(dict(context), ensure_ascii=False, sort_keys=True, default=str)},
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "pricegauger_ai_baseline_decision",
                    "schema": _decision_schema(),
                    "strict": True,
                }
            },
        },
        timeout=timeout_seconds,
    )
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        detail = response.text[:500].replace(api_key, "[redacted]")
        raise RuntimeError(f"OpenAI AI-baseline request failed ({response.status_code}): {detail}") from exc
    raw = response.json()
    parsed = json.loads(_response_output_text(raw))
    if not isinstance(parsed, dict):
        raise ValueError("AI baseline structured output must be an object")
    return parsed


def run_ai_baseline_shadow_once_v1(*, db_path: str = "pricegauger.db", now: datetime | None = None) -> int:
    """Persist one auditable GPT baseline decision for each currently managed product.

    The LLM only chooses target exposure. It never sizes or submits orders. Decisions
    are sampled on a 5-minute boundary from the existing canonical 1m/Cocktail clock.
    """
    if not using_postgres():
        return 0
    ensure_ai_baseline_schema_v1()
    key = openai_api_key().strip()
    if not key:
        return 0
    model = openai_market_model().strip() or "gpt-5-mini"
    current_time = _utc(now or datetime.now(timezone.utc))
    live = tuple(
        item for item in load_active_strategy_enrollments_v2()
        if item.execution_mode == EXECUTION_MODE_LIVE and item.enabled
    )
    by_instrument = {int(item.instrument_id): item for item in live}
    saved = 0
    for instrument_id in by_instrument:
        clock = _latest_cocktail_clock(instrument_id)
        if clock is None:
            continue
        market_name, action_at, price = clock
        epoch_minute = int(action_at.timestamp() // 60)
        if epoch_minute % DECISION_INTERVAL_MINUTES != 0:
            continue
        if current_time - action_at > timedelta(minutes=3):
            continue
        if _decision_exists(instrument_id, action_at):
            continue
        previous = load_latest_ai_decision_v1(instrument_id)
        current_state = STATE_FLAT if previous is None else previous.target_direction
        context = _compact_context(
            market_name,
            db_path=db_path,
            action_at=action_at,
            current_state=current_state,
        )
        serialized = json.dumps(context, ensure_ascii=False, sort_keys=True, default=str)
        context_hash = sha256(serialized.encode("utf-8")).hexdigest()
        result = _call_model(context=context, api_key=key, model=model)
        target = str(result["target_direction"])
        if target not in {STATE_LONG, STATE_SHORT, STATE_FLAT}:
            raise ValueError(f"AI baseline returned invalid direction: {target}")
        with connect() as db:
            db.execute(
                """
                INSERT INTO pg_v2_autotrader_ai_baseline_samples(
                    strategy_key, instrument_id, market_name, action_at, price,
                    model, prompt_version, target_direction, confidence,
                    horizon_minutes, summary, technical_case, news_case,
                    invalidation, context_hash, context_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (strategy_key, instrument_id, action_at) DO NOTHING
                """,
                (
                    STRATEGY_KEY, int(instrument_id), market_name, action_at, float(price),
                    model, PROMPT_VERSION, target, float(result["confidence"]),
                    int(result["horizon_minutes"]), str(result["summary"]),
                    str(result["technical_case"]), str(result["news_case"]),
                    str(result["invalidation"]), context_hash, serialized,
                ),
            )
        saved += 1
        LOGGER.info(
            "AI baseline decision market=%s action_at=%s target=%s confidence=%.2f model=%s",
            market_name, action_at.isoformat(), target, float(result["confidence"]), model,
        )
    return saved


def run_ai_baseline_shadow_forever_v1(*, db_path: str = "pricegauger.db", interval_seconds: int = 60) -> None:
    interval = max(30, int(interval_seconds))
    while True:
        started = time.monotonic()
        try:
            run_ai_baseline_shadow_once_v1(db_path=db_path)
        except Exception as exc:
            LOGGER.warning("AI baseline shadow cycle failed: %s", exc, exc_info=True)
        time.sleep(max(1.0, interval - (time.monotonic() - started)))


def load_ai_baseline_series_v1(
    *,
    instrument_id: int,
    seed_equity: float,
    currency: str,
    started_at: datetime,
    as_of: datetime,
    db_path: str = "pricegauger.db",
) -> ShadowBenchmarkSeriesV2 | None:
    ensure_ai_baseline_schema_v1()
    start = _utc(started_at)
    end = _utc(as_of)
    with connect() as db:
        rows = db.execute(
            """
            SELECT action_at, price, target_direction
            FROM pg_v2_autotrader_ai_baseline_samples
            WHERE strategy_key = ? AND instrument_id = ?
              AND action_at >= ? AND action_at <= ?
            ORDER BY action_at ASC
            """,
            (STRATEGY_KEY, int(instrument_id), start, end),
        ).fetchall()
    if not rows:
        return None
    decisions = []
    for row in rows:
        values = dict(row) if isinstance(row, dict) else {
            "action_at": row[0], "price": row[1], "target_direction": row[2]
        }
        decisions.append((_utc(values["action_at"]), float(values["price"]), str(values["target_direction"])))

    equity = float(seed_equity)
    first_at, first_price, state = decisions[0]
    points = [ShadowEquityPointV2(closed_at=first_at, equity=equity, position_state=state)]
    previous_price = first_price
    previous_at = first_at
    for action_at, price, next_state in decisions[1:]:
        if previous_price > 0:
            price_return = (float(price) / float(previous_price)) - 1.0
            equity = apply_shadow_return_v2(equity=equity, position_state=state, price_return=price_return)
        state = next_state
        previous_price = float(price)
        previous_at = action_at
        points.append(ShadowEquityPointV2(closed_at=action_at, equity=equity, position_state=state))

    bars = CanonicalMarketBarStoreV2(db_path).load_instrument_range(
        instrument_id=int(instrument_id),
        start=previous_at - timedelta(minutes=1),
        end=end,
        limit=10_000,
    )
    if bars:
        latest = bars[-1]
        latest_at = _utc(latest.bar_time).replace(second=0, microsecond=0) + timedelta(minutes=1)
        latest_price = float(latest.close)
        if latest_at > previous_at and previous_price > 0:
            price_return = (latest_price / previous_price) - 1.0
            equity = apply_shadow_return_v2(equity=equity, position_state=state, price_return=price_return)
            points.append(ShadowEquityPointV2(closed_at=latest_at, equity=equity, position_state=state))

    return ShadowBenchmarkSeriesV2(
        strategy_key=STRATEGY_KEY,
        execution_mode="SHADOW_ADAPTIVE",
        currency=str(currency),
        seed_equity=float(seed_equity),
        started_at=first_at,
        points=tuple(points),
    )


__all__ = [
    "AIBaselineDecisionV1",
    "DECISION_INTERVAL_MINUTES",
    "MAX_DECISION_AGE",
    "PROMPT_VERSION",
    "STRATEGY_KEY",
    "ai_decision_is_fresh_v1",
    "ensure_ai_baseline_schema_v1",
    "load_ai_baseline_series_v1",
    "load_latest_ai_decision_v1",
    "run_ai_baseline_shadow_forever_v1",
    "run_ai_baseline_shadow_once_v1",
]
