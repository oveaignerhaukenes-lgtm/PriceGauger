from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from context_snapshot_v2 import (
    SCOPE_GLOBAL,
    UNKNOWN,
    ContextDimensionV2,
    ContextEvidenceRefV2,
    ContextTargetStateV2,
    ContextSnapshotV2,
    build_context_snapshot_v2,
)
from news_context_engine import NewsContextAssessment
from telegram_flow_engine import ScoredTelegramPost, TelegramFlowAssessment


ADAPTER_VERSION = "context-adapter-v2-v1"

_ESCALATION_VALUE = {
    "escalating": 1.0,
    "stable": 0.0,
    "de-escalating": -1.0,
    "mixed": 0.0,
    "unclear": 0.0,
}


def _evidence_id(channel: str, message_id: str) -> str:
    return f"telegram:{str(channel).strip()}:{str(message_id).strip()}"


def _evidence_from_posts(
    posts: Iterable[ScoredTelegramPost],
    *,
    observed_at: str,
) -> tuple[ContextEvidenceRefV2, ...]:
    refs: dict[str, ContextEvidenceRefV2] = {}
    for post in posts:
        evidence_id = _evidence_id(post.channel, post.message_id)
        refs[evidence_id] = ContextEvidenceRefV2(
            evidence_id=evidence_id,
            source_kind="TELEGRAM",
            source_scope=SCOPE_GLOBAL,
            source_id=post.channel,
            observed_at=observed_at,
            published_at=post.published_at,
            tags=(post.event_key, post.relation),
        )
    return tuple(refs.values())


def _evidence_from_flow(flow: TelegramFlowAssessment) -> tuple[ContextEvidenceRefV2, ...]:
    refs: dict[str, ContextEvidenceRefV2] = {}
    for item in flow.contributions:
        evidence_id = _evidence_id(item.channel, item.message_id)
        refs[evidence_id] = ContextEvidenceRefV2(
            evidence_id=evidence_id,
            source_kind="TELEGRAM",
            source_scope=SCOPE_GLOBAL,
            source_id=item.channel,
            observed_at=flow.as_of,
            published_at=item.published_at,
            tags=(item.event_key,),
        )
    return tuple(refs.values())


def _news_dimensions(
    news: NewsContextAssessment | None,
    evidence_ids: tuple[str, ...],
) -> tuple[ContextDimensionV2, ...]:
    if news is None:
        return ()
    confidence = float(news.confidence)
    escalation = _ESCALATION_VALUE.get(str(news.escalation_direction).strip().lower(), 0.0)
    return (
        ContextDimensionV2("conflict_level", float(news.conflict_level), confidence, evidence_ids),
        ContextDimensionV2("fear_level", float(news.fear_level), confidence, evidence_ids),
        ContextDimensionV2("escalation_direction", escalation, confidence, evidence_ids),
        ContextDimensionV2("physical_supply_risk", float(news.physical_supply_risk), confidence, evidence_ids),
        ContextDimensionV2("narrative_saturation", float(news.narrative_saturation), confidence, evidence_ids),
        ContextDimensionV2("confirmation_quality", float(news.confirmation_quality), confidence, evidence_ids),
    )


def _target_states(
    flow: TelegramFlowAssessment,
    *,
    news: NewsContextAssessment | None,
) -> tuple[ContextTargetStateV2, ...]:
    selected_by_asset: dict[str, list] = defaultdict(list)
    for item in flow.contributions:
        if item.selected:
            selected_by_asset[item.asset].append(item)

    targets: list[ContextTargetStateV2] = []
    for asset in flow.assets:
        selected = selected_by_asset.get(asset.asset, [])
        evidence_ids = tuple(
            sorted({_evidence_id(item.channel, item.message_id) for item in selected})
        )
        novelty = max((float(item.novelty) for item in selected), default=0.0)
        event_risk = max(
            (
                min(
                    1.0,
                    float(item.impact)
                    * float(item.confidence)
                    * float(item.source_quality),
                )
                for item in selected
            ),
            default=0.0,
        )
        targets.append(
            ContextTargetStateV2(
                target_key=asset.asset,
                directional_bias=float(asset.normalized_score),
                confidence=float(asset.confidence),
                novelty=novelty,
                event_risk=event_risk,
                evidence_ids=evidence_ids,
                dimensions=_news_dimensions(news, evidence_ids),
                summary="",
            )
        )
    return tuple(targets)


def adapt_context_snapshot_v2(
    *,
    flow: TelegramFlowAssessment,
    news: NewsContextAssessment | None = None,
    posts: Iterable[ScoredTelegramPost] = (),
    scope_key: str = "global",
) -> ContextSnapshotV2:
    """Adapt existing semantic engines into the v2 Context public contract.

    This function is deliberately pure. It does not persist snapshots, invoke the
    legacy state runtime, call an LLM, read Technical Core, or perform execution.
    """

    post_refs = _evidence_from_posts(posts, observed_at=flow.as_of)
    evidence = post_refs or _evidence_from_flow(flow)

    coverage_start = news.coverage_start if news is not None else ""
    coverage_end = news.coverage_end if news is not None else ""
    regime_label = news.regime_label if news is not None else ""
    summary = news.summary if news is not None else ""
    engine_version = (
        f"{ADAPTER_VERSION}|flow={flow.engine_version}"
        + (f"|news={news.engine_version}" if news is not None else "")
    )

    return build_context_snapshot_v2(
        as_of=flow.as_of,
        engine_version=engine_version,
        scope_key=scope_key,
        freshness_status=UNKNOWN,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        evidence=evidence,
        targets=_target_states(flow, news=news),
        regime_label=regime_label,
        summary=summary,
    )
