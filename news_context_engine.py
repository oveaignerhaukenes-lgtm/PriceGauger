from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

import pandas as pd
import requests

from config import openai_api_key, openai_market_model
from telegram_query_builder import TelegramSearchPlan

_RESPONSES_URL = "https://api.openai.com/v1/responses"
ENGINE_VERSION = "news-context-v1"
WINDOW_HOURS = (1, 4, 12, 24, 168)


@dataclass(frozen=True, slots=True)
class NewsWindow:
    hours: int
    post_count: int
    first_post_at: str
    last_post_at: str
    posts: tuple[str, ...]

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class NewsContextAssessment:
    as_of: str
    engine_version: str
    source_channel: str
    source_post_count: int
    coverage_start: str
    coverage_end: str
    coverage_warning: str
    conflict_level: float
    fear_level: float
    escalation_direction: str
    physical_supply_risk: float
    narrative_saturation: float
    confirmation_quality: float
    regime_label: str
    active_drivers: tuple[str, ...]
    counter_signals: tuple[str, ...]
    unresolved_questions: tuple[str, ...]
    summary: str
    confidence: float
    model: str
    windows: tuple[NewsWindow, ...]

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["windows"] = [item.to_record() for item in self.windows]
        return record


def news_context_from_record(record: dict[str, Any]) -> NewsContextAssessment:
    """Rehydrate a persisted assessment without coupling callers to its schema."""
    payload = dict(record)
    payload["active_drivers"] = tuple(payload.get("active_drivers") or ())
    payload["counter_signals"] = tuple(payload.get("counter_signals") or ())
    payload["unresolved_questions"] = tuple(payload.get("unresolved_questions") or ())
    windows: list[NewsWindow] = []
    for item in payload.get("windows") or ():
        if isinstance(item, NewsWindow):
            windows.append(item)
            continue
        window = dict(item)
        window["posts"] = tuple(window.get("posts") or ())
        windows.append(NewsWindow(**window))
    payload["windows"] = tuple(windows)
    return NewsContextAssessment(**payload)


def _as_utc(value: str | datetime | pd.Timestamp | None) -> pd.Timestamp:
    if value is None:
        return pd.Timestamp.now(tz="UTC")
    parsed = pd.Timestamp(value)
    if parsed.tzinfo is None:
        return parsed.tz_localize("UTC")
    return parsed.tz_convert("UTC")


def build_windows(
    plans: Iterable[TelegramSearchPlan],
    *,
    as_of: str | datetime | pd.Timestamp | None = None,
) -> tuple[NewsWindow, ...]:
    cutoff = _as_utc(as_of)
    rows: list[tuple[pd.Timestamp, str]] = []
    for plan in plans:
        if not plan.published_at:
            continue
        published = _as_utc(plan.published_at)
        if published <= cutoff:
            rows.append((published, plan.message_text))
    rows.sort(key=lambda item: item[0])

    windows: list[NewsWindow] = []
    for hours in WINDOW_HOURS:
        start = cutoff - pd.Timedelta(hours=hours)
        selected = [(ts, text) for ts, text in rows if ts >= start]
        windows.append(
            NewsWindow(
                hours=hours,
                post_count=len(selected),
                first_post_at=selected[0][0].isoformat() if selected else "",
                last_post_at=selected[-1][0].isoformat() if selected else "",
                posts=tuple(text for _, text in selected),
            )
        )
    return tuple(windows)


def _response_text(payload: dict[str, Any]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    parts: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if isinstance(content, dict) and content.get("type") == "output_text" and content.get("text"):
                parts.append(str(content["text"]))
    if not parts:
        raise ValueError("OpenAI response contained no output text")
    return "\n".join(parts)


def _score(value: Any, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not 0 <= result <= 1:
        raise ValueError(f"{field} must be between 0 and 1")
    return result


def build_prompt(*, windows: tuple[NewsWindow, ...], as_of: pd.Timestamp, channel: str) -> str:
    blocks: list[str] = []
    for window in windows:
        posts = "\n".join(f"- {text}" for text in window.posts[-30:]) or "- No posts available"
        blocks.append(f"WINDOW {window.hours} HOURS | posts={window.post_count}\n{posts}")
    return f"""Assess the rolling geopolitical and market-relevant news context as of {as_of.isoformat()}.
Source channel: {channel}

Use the windows jointly. Distinguish new impulse from the broader regime. Do not infer facts absent from the posts. Scores are 0 to 1.

Return:
- conflict_level
- fear_level
- escalation_direction: escalating, stable, de-escalating, mixed or unclear
- physical_supply_risk
- narrative_saturation: how repeatedly the same theme is already circulating
- confirmation_quality
- regime_label
- active_drivers: concise list
- counter_signals: concise list
- unresolved_questions: concise list
- summary
- confidence

{chr(10).join(blocks)}
"""


class OpenAINewsContextEngine:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        timeout: int = 60,
        session: Any = requests,
    ) -> None:
        self.api_key = (api_key if api_key is not None else openai_api_key()).strip()
        self.model = (model if model is not None else openai_market_model()).strip()
        self.timeout = timeout
        self.session = session
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is required for news context assessment")

    def assess(
        self,
        plans: Iterable[TelegramSearchPlan],
        *,
        channel: str,
        as_of: str | datetime | pd.Timestamp | None = None,
    ) -> NewsContextAssessment:
        plan_list = list(plans)
        cutoff = _as_utc(as_of)
        windows = build_windows(plan_list, as_of=cutoff)
        dated = sorted(_as_utc(plan.published_at) for plan in plan_list if plan.published_at and _as_utc(plan.published_at) <= cutoff)
        coverage_start = dated[0].isoformat() if dated else ""
        coverage_end = dated[-1].isoformat() if dated else ""
        coverage_hours = (cutoff - dated[0]).total_seconds() / 3600 if dated else 0
        coverage_warning = ""
        if coverage_hours < 168:
            coverage_warning = "Source retrieval does not cover the full requested seven-day regime window."

        response = self.session.post(
            _RESPONSES_URL,
            timeout=self.timeout,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={
                "model": self.model,
                "input": build_prompt(windows=windows, as_of=cutoff, channel=channel),
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "news_context_assessment",
                        "strict": True,
                        "schema": {
                            "type": "object",
                            "properties": {
                                "conflict_level": {"type": "number", "minimum": 0, "maximum": 1},
                                "fear_level": {"type": "number", "minimum": 0, "maximum": 1},
                                "escalation_direction": {"type": "string", "enum": ["escalating", "stable", "de-escalating", "mixed", "unclear"]},
                                "physical_supply_risk": {"type": "number", "minimum": 0, "maximum": 1},
                                "narrative_saturation": {"type": "number", "minimum": 0, "maximum": 1},
                                "confirmation_quality": {"type": "number", "minimum": 0, "maximum": 1},
                                "regime_label": {"type": "string"},
                                "active_drivers": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
                                "counter_signals": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
                                "unresolved_questions": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
                                "summary": {"type": "string"},
                                "confidence": {"type": "number", "minimum": 0, "maximum": 1}
                            },
                            "required": ["conflict_level", "fear_level", "escalation_direction", "physical_supply_risk", "narrative_saturation", "confirmation_quality", "regime_label", "active_drivers", "counter_signals", "unresolved_questions", "summary", "confidence"],
                            "additionalProperties": False
                        }
                    }
                }
            },
        )
        response.raise_for_status()
        parsed = json.loads(_response_text(response.json()))
        return NewsContextAssessment(
            as_of=cutoff.isoformat(),
            engine_version=ENGINE_VERSION,
            source_channel=channel,
            source_post_count=len(plan_list),
            coverage_start=coverage_start,
            coverage_end=coverage_end,
            coverage_warning=coverage_warning,
            conflict_level=_score(parsed.get("conflict_level"), "conflict_level"),
            fear_level=_score(parsed.get("fear_level"), "fear_level"),
            escalation_direction=str(parsed.get("escalation_direction") or "unclear"),
            physical_supply_risk=_score(parsed.get("physical_supply_risk"), "physical_supply_risk"),
            narrative_saturation=_score(parsed.get("narrative_saturation"), "narrative_saturation"),
            confirmation_quality=_score(parsed.get("confirmation_quality"), "confirmation_quality"),
            regime_label=str(parsed.get("regime_label") or "unclear").strip(),
            active_drivers=tuple(str(item).strip() for item in parsed.get("active_drivers") or [] if str(item).strip()),
            counter_signals=tuple(str(item).strip() for item in parsed.get("counter_signals") or [] if str(item).strip()),
            unresolved_questions=tuple(str(item).strip() for item in parsed.get("unresolved_questions") or [] if str(item).strip()),
            summary=str(parsed.get("summary") or "").strip(),
            confidence=_score(parsed.get("confidence"), "confidence"),
            model=self.model,
            windows=windows,
        )
