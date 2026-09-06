from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

import requests

from config import openai_market_model
from database import connect
from indicator_guide_v1 import quick_indicator_read_v1
from openai_market_provider import OPENAI_RESPONSES_URL, _response_output_text
from realtime_market_data import RealtimeMarketDataStore
from recipe_registry_v2 import TA_ONLY_V1
from trading_desk import TIMEFRAME_MINUTES, resample_bars
from trading_desk_indicators import INDICATOR_OPTIONS, calculate_indicators
from ui_workspace_state_v2 import load_ui_workspace_state_v2
from workspace_loader_v2 import load_workspace_v2


INDICATOR_AI_SESSION_KEY = "tradingdesk-indicator-ai-enabled"
INDICATOR_AI_STATE_FIELD = "indicator_ai_enabled"
INDICATOR_AI_RECIPE = "indicator-ai-read-v1"


@dataclass(frozen=True, slots=True)
class IndicatorAiSnapshotV1:
    market: str
    timeframe: str
    source_bar_time: str
    indicator_set_key: str
    assessments: dict[str, str]
    model: str
    created_at: str | None = None


def _ensure_schema() -> None:
    with connect() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS pg_v2_indicator_ai_insights (
                market_id INTEGER NOT NULL,
                timeframe TEXT NOT NULL,
                source_bar_time TIMESTAMPTZ NOT NULL,
                indicator_set_key TEXT NOT NULL,
                assessments_json TEXT NOT NULL,
                model TEXT NOT NULL,
                recipe_version TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (market_id, timeframe, source_bar_time, indicator_set_key)
            )
            """
        )


def _market_id(name: str) -> int | None:
    with connect() as db:
        row = db.execute(
            "SELECT market_id FROM pg_v2_markets WHERE name = ? AND active = TRUE",
            (str(name),),
        ).fetchone()
    if row is None:
        return None
    if isinstance(row, Mapping):
        return int(row["market_id"])
    return int(row[0])


def _indicator_set_key(names: Sequence[str]) -> str:
    normalized = tuple(sorted({str(item) for item in names if str(item) in INDICATOR_OPTIONS}))
    return sha256(json.dumps(normalized, separators=(",", ":")).encode("utf-8")).hexdigest()[:20]


def load_latest_indicator_ai_v1(
    *,
    market: str,
    timeframe: str,
    indicator_names: Sequence[str] | None = None,
) -> IndicatorAiSnapshotV1 | None:
    _ensure_schema()
    market_id = _market_id(market)
    if market_id is None:
        return None
    parameters: list[Any] = [market_id, str(timeframe)]
    where_set = ""
    if indicator_names is not None:
        where_set = "AND indicator_set_key = ?"
        parameters.append(_indicator_set_key(indicator_names))
    with connect() as db:
        row = db.execute(
            f"""
            SELECT source_bar_time, indicator_set_key, assessments_json, model, created_at
            FROM pg_v2_indicator_ai_insights
            WHERE market_id = ? AND timeframe = ? {where_set}
            ORDER BY source_bar_time DESC, created_at DESC
            LIMIT 1
            """,
            tuple(parameters),
        ).fetchone()
    if row is None:
        return None
    item = dict(row) if not isinstance(row, Mapping) else row
    try:
        assessments = json.loads(str(item["assessments_json"]))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(assessments, dict):
        return None
    return IndicatorAiSnapshotV1(
        market=str(market),
        timeframe=str(timeframe),
        source_bar_time=str(item["source_bar_time"]),
        indicator_set_key=str(item["indicator_set_key"]),
        assessments={str(key): str(value) for key, value in assessments.items()},
        model=str(item["model"]),
        created_at=None if item.get("created_at") is None else str(item["created_at"]),
    )


def _persist_snapshot(
    *,
    market_id: int,
    timeframe: str,
    source_bar_time: str,
    indicator_set_key: str,
    assessments: Mapping[str, str],
    model: str,
) -> None:
    _ensure_schema()
    encoded = json.dumps(dict(assessments), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with connect() as db:
        db.execute(
            """
            INSERT INTO pg_v2_indicator_ai_insights(
                market_id, timeframe, source_bar_time, indicator_set_key,
                assessments_json, model, recipe_version, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT (market_id, timeframe, source_bar_time, indicator_set_key) DO NOTHING
            """,
            (
                int(market_id),
                str(timeframe),
                str(source_bar_time),
                str(indicator_set_key),
                encoded,
                str(model),
                INDICATOR_AI_RECIPE,
            ),
        )


def _output_schema(indicator_names: Sequence[str]) -> dict[str, Any]:
    properties = {
        str(name): {"type": "string", "maxLength": 150}
        for name in indicator_names
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {"assessments": {
            "type": "object",
            "additionalProperties": False,
            "properties": properties,
            "required": list(properties),
        }},
        "required": ["assessments"],
    }


def _request_assessments(
    *,
    api_key: str,
    model: str,
    payload: Mapping[str, Any],
    indicator_names: Sequence[str],
    timeout_seconds: float = 35.0,
) -> dict[str, str]:
    if not api_key.strip():
        raise ValueError("OPENAI_API_KEY is not configured")
    response = requests.post(
        OPENAI_RESPONSES_URL,
        headers={
            "Authorization": f"Bearer {api_key.strip()}",
            "Content-Type": "application/json",
        },
        json={
            "model": str(model),
            "store": False,
            "input": [
                {
                    "role": "system",
                    "content": (
                        "Du er PriceGaugers forklarende tekniske indikatorlag. Bruk bare dataene du får. "
                        "Skriv én ekstremt kort norsk vurdering per indikator, maks én setning. "
                        "Forklar hva indikatoren sier nå i det oppgitte regimet; ikke gi ordre, sizing, "
                        "pris-target eller kjøp/selg-instruks. Ekstreme oscillatornivåer er ikke automatisk reversal."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(dict(payload), ensure_ascii=False, sort_keys=True),
                },
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "indicator_ai_assessments_v1",
                    "schema": _output_schema(indicator_names),
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
        raise RuntimeError(f"OpenAI indicator request failed ({response.status_code}): {detail}") from exc
    raw = response.json()
    parsed = json.loads(_response_output_text(raw))
    if not isinstance(parsed, Mapping) or not isinstance(parsed.get("assessments"), Mapping):
        raise ValueError("indicator AI response missing assessments")
    assessments: dict[str, str] = {}
    for name in indicator_names:
        text = str(parsed["assessments"].get(name, "")).strip()
        if not text:
            raise ValueError(f"indicator AI response missing {name}")
        if len(text) > 150:
            raise ValueError(f"indicator AI response too long for {name}")
        assessments[str(name)] = text
    return assessments


def _source_payload(*, market: str, timeframe: str, bars, technical, workspace, indicator_names: Sequence[str]) -> dict[str, Any]:
    latest_close = float(bars[-1].close)
    return {
        "market": str(market),
        "timeframe": str(timeframe),
        "source_bar_time": bars[-1].bar_time.isoformat(),
        "latest_close": latest_close,
        "regime": {
            "trend": workspace.technical_state.trend_state,
            "momentum": workspace.technical_state.momentum_state,
            "volatility": workspace.technical_state.volatility_state,
            "structure": workspace.technical_state.structure_state,
            "score": workspace.technical_state.score,
            "confidence": workspace.technical_state.confidence,
        },
        "indicator_reads": {
            name: quick_indicator_read_v1(name, technical, latest_close=latest_close)
            for name in indicator_names
        },
    }


def refresh_indicator_ai_once_v1(
    *,
    api_key: str,
    db_path: str = "pricegauger.db",
) -> int:
    """Materialize one opt-in indicator explanation snapshot for the active TradingDesk view.

    The browser never calls OpenAI. A safe persisted UI preference merely tells the
    background worker whether this explanatory read-model should be refreshed.
    """
    if not api_key.strip():
        return 0
    ui = load_ui_workspace_state_v2("tradingdesk")
    state = {} if ui is None else dict(ui.state)
    if not bool(state.get(INDICATOR_AI_STATE_FIELD, False)):
        return 0

    market = str(state.get("selected_market") or "").strip()
    timeframe = str(state.get("timeframe") or "5m").strip()
    if not market or timeframe not in TIMEFRAME_MINUTES:
        return 0
    indicator_names = [
        str(item) for item in state.get("indicators", ())
        if str(item) in INDICATOR_OPTIONS
    ]
    if not indicator_names:
        return 0

    market_id = _market_id(market)
    if market_id is None:
        return 0
    workspace = load_workspace_v2(
        market_id=market_id,
        analysis_recipe_id=TA_ONLY_V1.recipe_id,
        restore_cached_layers=False,
    )

    minutes = int(TIMEFRAME_MINUTES[timeframe])
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=max(24, int(minutes * 180 / 60) + 6))
    raw = RealtimeMarketDataStore(db_path).load_range(market=market, start=start, end=end, limit=20000)
    bars = tuple(resample_bars(raw, timeframe=timeframe))
    if len(bars) < 30:
        return 0
    technical = calculate_indicators(bars)
    source_bar_time = bars[-1].bar_time.isoformat()
    set_key = _indicator_set_key(indicator_names)

    _ensure_schema()
    with connect() as db:
        existing = db.execute(
            """
            SELECT 1 FROM pg_v2_indicator_ai_insights
            WHERE market_id = ? AND timeframe = ? AND source_bar_time = ? AND indicator_set_key = ?
            LIMIT 1
            """,
            (market_id, timeframe, source_bar_time, set_key),
        ).fetchone()
    if existing is not None:
        return 0

    payload = _source_payload(
        market=market,
        timeframe=timeframe,
        bars=bars,
        technical=technical,
        workspace=workspace,
        indicator_names=indicator_names,
    )
    model = openai_market_model()
    assessments = _request_assessments(
        api_key=api_key,
        model=model,
        payload=payload,
        indicator_names=indicator_names,
    )
    _persist_snapshot(
        market_id=market_id,
        timeframe=timeframe,
        source_bar_time=source_bar_time,
        indicator_set_key=set_key,
        assessments=assessments,
        model=model,
    )
    return 1


__all__ = [
    "INDICATOR_AI_RECIPE",
    "INDICATOR_AI_SESSION_KEY",
    "INDICATOR_AI_STATE_FIELD",
    "IndicatorAiSnapshotV1",
    "load_latest_indicator_ai_v1",
    "refresh_indicator_ai_once_v1",
]
