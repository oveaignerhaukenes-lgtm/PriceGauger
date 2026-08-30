from __future__ import annotations

from dataclasses import replace
import inspect

import context_adapter_v2
from context_snapshot_v2 import SCOPE_GLOBAL, UNKNOWN
from news_context_engine import NewsContextAssessment, NewsWindow
from telegram_flow_engine import (
    AssetFlowAssessment,
    AssetPostScore,
    FlowContribution,
    ScoredTelegramPost,
    TelegramFlowAssessment,
)


def _post() -> ScoredTelegramPost:
    return ScoredTelegramPost(
        message_id="Middle_East_Spectator:42",
        channel="Middle_East_Spectator",
        published_at="2026-08-16T20:00:00Z",
        text="Supply disruption reported.",
        event_key="supply-disruption",
        relation="new",
        novelty=0.8,
        source_quality=0.9,
        scores=(
            AssetPostScore(
                asset="Gold",
                direction=0.7,
                impact=0.6,
                confidence=0.8,
                horizon_hours=4.0,
                rationale="Risk-off impulse",
            ),
        ),
    )


def _flow() -> TelegramFlowAssessment:
    contribution = FlowContribution(
        asset="Gold",
        event_key="supply-disruption",
        message_id="Middle_East_Spectator:42",
        channel="Middle_East_Spectator",
        published_at="2026-08-16T20:00:00Z",
        direction=0.7,
        impact=0.6,
        confidence=0.8,
        decay=1.0,
        channel_weight=1.0,
        novelty=0.8,
        source_quality=0.9,
        raw_score=0.3024,
        selected=True,
        rationale="Risk-off impulse",
    )
    return TelegramFlowAssessment(
        as_of="2026-08-16T20:05:00Z",
        engine_version="telegram-flow-v1",
        source_channels=("Middle_East_Spectator",),
        post_count=1,
        event_cluster_count=1,
        assets=(
            AssetFlowAssessment(
                asset="Gold",
                flow_score=0.3024,
                normalized_score=0.65,
                direction="LONG_BIAS",
                confidence=0.72,
                bullish_events=1,
                bearish_events=0,
                neutral_events=0,
                selected_event_count=1,
                raw_post_count=1,
                top_drivers=("risk-off",),
            ),
        ),
        contributions=(contribution,),
        model="test-model",
    )


def _news() -> NewsContextAssessment:
    return NewsContextAssessment(
        as_of="2026-08-16T20:05:00Z",
        engine_version="news-context-v1",
        source_channel="Middle_East_Spectator",
        source_post_count=1,
        coverage_start="2026-08-16T19:00:00Z",
        coverage_end="2026-08-16T20:00:00Z",
        coverage_warning="",
        conflict_level=0.7,
        fear_level=0.6,
        escalation_direction="escalating",
        physical_supply_risk=0.5,
        narrative_saturation=0.3,
        confirmation_quality=0.8,
        regime_label="elevated geopolitical risk",
        active_drivers=("supply risk",),
        counter_signals=(),
        unresolved_questions=(),
        summary="Escalation with supply risk.",
        confidence=0.75,
        model="test-model",
        windows=(NewsWindow(1, 1, "2026-08-16T20:00:00Z", "2026-08-16T20:00:00Z", ("post",)),),
    )


def test_adapter_preserves_flow_pressure_and_news_regime():
    snapshot = context_adapter_v2.adapt_context_snapshot_v2(
        flow=_flow(),
        news=_news(),
        posts=(_post(),),
    )

    assert snapshot.freshness_status == UNKNOWN
    assert snapshot.regime_label == "elevated geopolitical risk"
    assert snapshot.coverage_start == "2026-08-16T19:00:00+00:00"
    assert len(snapshot.targets) == 1
    gold = snapshot.targets[0]
    assert gold.target_key == "Gold"
    assert gold.directional_bias == 0.3024
    assert gold.confidence == 0.72
    assert gold.novelty == 0.8
    assert gold.event_risk == 0.6 * 0.8 * 0.9
    dimensions = {item.name: item.value for item in gold.dimensions}
    assert dimensions["physical_supply_risk"] == 0.5
    assert dimensions["escalation_direction"] == 1.0


def test_adapter_does_not_turn_one_weak_directional_event_into_full_pressure():
    flow = _flow()
    weak_asset = replace(
        flow.assets[0],
        flow_score=0.04,
        normalized_score=1.0,
        confidence=0.06,
    )
    snapshot = context_adapter_v2.adapt_context_snapshot_v2(
        flow=replace(flow, assets=(weak_asset,)),
        posts=(_post(),),
    )

    gold = snapshot.targets[0]
    assert gold.directional_bias == 0.04
    assert gold.confidence == 0.06


def test_adapter_emits_explicit_global_telegram_provenance():
    snapshot = context_adapter_v2.adapt_context_snapshot_v2(
        flow=_flow(),
        posts=(_post(),),
    )

    assert len(snapshot.evidence) == 1
    evidence = snapshot.evidence[0]
    assert evidence.source_scope == SCOPE_GLOBAL
    assert evidence.source_kind == "TELEGRAM"
    assert evidence.source_id == "Middle_East_Spectator"
    assert snapshot.targets[0].evidence_ids == (evidence.evidence_id,)


def test_adapter_can_fall_back_to_flow_contributions_without_raw_posts():
    snapshot = context_adapter_v2.adapt_context_snapshot_v2(flow=_flow())

    assert len(snapshot.evidence) == 1
    assert snapshot.targets[0].evidence_ids == (snapshot.evidence[0].evidence_id,)


def test_adapter_has_no_legacy_runtime_technical_or_execution_authority():
    source = inspect.getsource(context_adapter_v2)

    forbidden = (
        "state_runtime_pipeline",
        "process_flow_snapshot",
        "technical_core",
        "AutoTrader",
        "place_order",
        "precheck",
        "database.connect",
    )
    for token in forbidden:
        assert token not in source
