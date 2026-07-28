from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping

import pandas as pd
import requests

from config import openai_api_key, openai_market_model
from telegram_query_builder import TelegramSearchPlan

_RESPONSES_URL = "https://api.openai.com/v1/responses"
ENGINE_VERSION = "telegram-flow-v1"
ASSETS = ("Brent", "Gold", "Silver", "DXY", "Natural Gas")
RELATIONS = ("new", "update", "confirmation", "denial", "duplicate")


@dataclass(frozen=True, slots=True)
class AssetPostScore:
    asset: str
    direction: float
    impact: float
    confidence: float
    horizon_hours: float
    rationale: str

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ScoredTelegramPost:
    message_id: str
    channel: str
    published_at: str
    text: str
    event_key: str
    relation: str
    novelty: float
    source_quality: float
    scores: tuple[AssetPostScore, ...]

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["scores"] = [item.to_record() for item in self.scores]
        return record


@dataclass(frozen=True, slots=True)
class FlowContribution:
    asset: str
    event_key: str
    message_id: str
    channel: str
    published_at: str
    direction: float
    impact: float
    confidence: float
    decay: float
    channel_weight: float
    novelty: float
    source_quality: float
    raw_score: float
    selected: bool
    rationale: str

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AssetFlowAssessment:
    asset: str
    flow_score: float
    normalized_score: float
    direction: str
    confidence: float
    bullish_events: int
    bearish_events: int
    neutral_events: int
    selected_event_count: int
    raw_post_count: int
    top_drivers: tuple[str, ...]

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TelegramFlowAssessment:
    as_of: str
    engine_version: str
    source_channels: tuple[str, ...]
    post_count: int
    event_cluster_count: int
    assets: tuple[AssetFlowAssessment, ...]
    contributions: tuple[FlowContribution, ...]
    model: str

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["assets"] = [item.to_record() for item in self.assets]
        record["contributions"] = [item.to_record() for item in self.contributions]
        return record


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


def _bounded(value: Any, field: str, low: float = 0.0, high: float = 1.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not low <= result <= high:
        raise ValueError(f"{field} must be between {low} and {high}")
    return result


def build_scoring_prompt(posts: list[tuple[str, TelegramSearchPlan]]) -> str:
    blocks = []
    for channel, plan in posts:
        blocks.append(
            f"MESSAGE_ID={plan.message_id}\nCHANNEL={channel}\nPUBLISHED={plan.published_at}\nTEXT={plan.message_text}"
        )
    return f"""Score each Telegram post as a potential incremental market impulse.

The selected Telegram channels are intentionally user-chosen and may have a topical or directional bias. Do not neutralize that choice, but score what the post itself adds to the information state. Other news and prices will be added by separate engines.

For each post:
- event_key: a compact stable semantic key shared by posts about the same underlying event.
- relation: new, update, confirmation, denial or duplicate relative to the other supplied posts.
- novelty: how much new information this post adds, 0 to 1.
- source_quality: confidence that the post accurately states the event, 0 to 1.
- score every listed asset: {', '.join(ASSETS)}.
- direction ranges from -1 (strong bearish pressure) to +1 (strong bullish pressure).
- impact is expected market relevance, 0 to 1.
- confidence is confidence in the sign and mechanism, 0 to 1.
- horizon_hours is the main expected reaction horizon, 0.25 to 168.
- rationale must be concise and causal.

Important:
- Score the incremental effect, not whether the asset is generally attractive.
- A denial or de-escalatory update can reverse an earlier impulse.
- A duplicate should have novelty near zero.
- Do not infer facts absent from the supplied posts.

POSTS
{chr(10).join(blocks)}
"""


class OpenAITelegramFlowScorer:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        timeout: int = 90,
        session: Any = requests,
    ) -> None:
        self.api_key = (api_key if api_key is not None else openai_api_key()).strip()
        self.model = (model if model is not None else openai_market_model()).strip()
        self.timeout = timeout
        self.session = session
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is required for Telegram flow scoring")

    def score(self, posts: list[tuple[str, TelegramSearchPlan]]) -> list[ScoredTelegramPost]:
        if not posts:
            return []
        response = self.session.post(
            _RESPONSES_URL,
            timeout=self.timeout,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={
                "model": self.model,
                "input": build_scoring_prompt(posts),
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "telegram_flow_scores",
                        "strict": True,
                        "schema": {
                            "type": "object",
                            "properties": {
                                "posts": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "message_id": {"type": "string"},
                                            "event_key": {"type": "string"},
                                            "relation": {"type": "string", "enum": list(RELATIONS)},
                                            "novelty": {"type": "number", "minimum": 0, "maximum": 1},
                                            "source_quality": {"type": "number", "minimum": 0, "maximum": 1},
                                            "scores": {
                                                "type": "array",
                                                "items": {
                                                    "type": "object",
                                                    "properties": {
                                                        "asset": {"type": "string", "enum": list(ASSETS)},
                                                        "direction": {"type": "number", "minimum": -1, "maximum": 1},
                                                        "impact": {"type": "number", "minimum": 0, "maximum": 1},
                                                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                                                        "horizon_hours": {"type": "number", "minimum": 0.25, "maximum": 168},
                                                        "rationale": {"type": "string"}
                                                    },
                                                    "required": ["asset", "direction", "impact", "confidence", "horizon_hours", "rationale"],
                                                    "additionalProperties": False
                                                },
                                                "minItems": len(ASSETS),
                                                "maxItems": len(ASSETS)
                                            }
                                        },
                                        "required": ["message_id", "event_key", "relation", "novelty", "source_quality", "scores"],
                                        "additionalProperties": False
                                    }
                                }
                            },
                            "required": ["posts"],
                            "additionalProperties": False
                        }
                    }
                }
            },
        )
        response.raise_for_status()
        parsed = json.loads(_response_text(response.json()))
        source_by_id = {str(plan.message_id): (channel, plan) for channel, plan in posts}
        results: list[ScoredTelegramPost] = []
        for row in parsed.get("posts") or []:
            message_id = str(row.get("message_id") or "")
            if message_id not in source_by_id:
                continue
            channel, plan = source_by_id[message_id]
            scores = tuple(
                AssetPostScore(
                    asset=str(item.get("asset") or ""),
                    direction=_bounded(item.get("direction"), "direction", -1.0, 1.0),
                    impact=_bounded(item.get("impact"), "impact"),
                    confidence=_bounded(item.get("confidence"), "confidence"),
                    horizon_hours=_bounded(item.get("horizon_hours"), "horizon_hours", 0.25, 168.0),
                    rationale=str(item.get("rationale") or "").strip(),
                )
                for item in row.get("scores") or []
            )
            results.append(
                ScoredTelegramPost(
                    message_id=message_id,
                    channel=channel,
                    published_at=plan.published_at,
                    text=plan.message_text,
                    event_key=str(row.get("event_key") or message_id).strip(),
                    relation=str(row.get("relation") or "new"),
                    novelty=_bounded(row.get("novelty"), "novelty"),
                    source_quality=_bounded(row.get("source_quality"), "source_quality"),
                    scores=scores,
                )
            )
        return results


def _as_utc(value: str | datetime | pd.Timestamp | None) -> pd.Timestamp:
    if value is None:
        return pd.Timestamp.now(tz="UTC")
    parsed = pd.Timestamp(value)
    if parsed.tzinfo is None:
        return parsed.tz_localize("UTC")
    return parsed.tz_convert("UTC")


def aggregate_scored_posts(
    posts: Iterable[ScoredTelegramPost],
    *,
    channel_weights: Mapping[str, float] | None = None,
    as_of: str | datetime | pd.Timestamp | None = None,
    half_life_hours: float = 4.0,
) -> TelegramFlowAssessment:
    post_list = list(posts)
    cutoff = _as_utc(as_of)
    weights = {str(key): max(0.0, float(value)) for key, value in (channel_weights or {}).items()}
    contributions: list[FlowContribution] = []

    for post in post_list:
        published = _as_utc(post.published_at) if post.published_at else cutoff
        age_hours = max(0.0, (cutoff - published).total_seconds() / 3600.0)
        decay = 0.5 ** (age_hours / max(half_life_hours, 0.01))
        channel_weight = weights.get(post.channel, 1.0)
        novelty = 0.0 if post.relation == "duplicate" else post.novelty
        for score in post.scores:
            raw = (
                score.direction
                * score.impact
                * score.confidence
                * decay
                * channel_weight
                * novelty
                * post.source_quality
            )
            contributions.append(
                FlowContribution(
                    asset=score.asset,
                    event_key=post.event_key,
                    message_id=post.message_id,
                    channel=post.channel,
                    published_at=post.published_at,
                    direction=score.direction,
                    impact=score.impact,
                    confidence=score.confidence,
                    decay=round(decay, 6),
                    channel_weight=channel_weight,
                    novelty=novelty,
                    source_quality=post.source_quality,
                    raw_score=round(raw, 6),
                    selected=False,
                    rationale=score.rationale,
                )
            )

    # One principal contribution per underlying event and asset prevents reposts from
    # multiplying the signal. Confirmations/updates improve the chosen event's strength
    # modestly, while denials can win if they carry the larger absolute contribution.
    selected_indices: set[int] = set()
    groups: dict[tuple[str, str], list[int]] = {}
    for index, item in enumerate(contributions):
        groups.setdefault((item.asset, item.event_key), []).append(index)
    for indices in groups.values():
        winner = max(indices, key=lambda idx: abs(contributions[idx].raw_score))
        selected_indices.add(winner)

    final_contributions = tuple(
        FlowContribution(**{**item.to_record(), "selected": index in selected_indices})
        for index, item in enumerate(contributions)
    )

    assessments: list[AssetFlowAssessment] = []
    for asset in ASSETS:
        selected = [item for item in final_contributions if item.asset == asset and item.selected]
        total = sum(item.raw_score for item in selected)
        absolute = sum(abs(item.raw_score) for item in selected)
        normalized = total / absolute if absolute > 0 else 0.0
        if normalized >= 0.18:
            direction = "LONG_BIAS"
        elif normalized <= -0.18:
            direction = "SHORT_BIAS"
        else:
            direction = "NEUTRAL"
        confidence = min(1.0, absolute / 1.5) * min(1.0, len(selected) / 4.0)
        ordered = sorted(selected, key=lambda item: abs(item.raw_score), reverse=True)
        drivers = tuple(
            f"{item.raw_score:+.2f} · {item.channel} · {item.rationale}" for item in ordered[:5]
        )
        assessments.append(
            AssetFlowAssessment(
                asset=asset,
                flow_score=round(total, 4),
                normalized_score=round(normalized, 4),
                direction=direction,
                confidence=round(confidence, 4),
                bullish_events=sum(item.raw_score > 0 for item in selected),
                bearish_events=sum(item.raw_score < 0 for item in selected),
                neutral_events=sum(item.raw_score == 0 for item in selected),
                selected_event_count=len(selected),
                raw_post_count=len(post_list),
                top_drivers=drivers,
            )
        )

    return TelegramFlowAssessment(
        as_of=cutoff.isoformat(),
        engine_version=ENGINE_VERSION,
        source_channels=tuple(dict.fromkeys(post.channel for post in post_list)),
        post_count=len(post_list),
        event_cluster_count=len({post.event_key for post in post_list}),
        assets=tuple(assessments),
        contributions=final_contributions,
        model="",
    )
