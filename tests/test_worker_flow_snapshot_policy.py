from dataclasses import replace

from telegram_flow_engine import AssetFlowAssessment, TelegramFlowAssessment
from worker import _snapshot_is_informative


def _assessment(
    *,
    as_of: str = "2026-07-30T10:00:00+00:00",
    flow_score: float = 0.25,
    direction: str = "LONG_BIAS",
    post_count: int = 10,
    cluster_count: int = 7,
) -> TelegramFlowAssessment:
    asset = AssetFlowAssessment(
        asset="Brent",
        flow_score=flow_score,
        normalized_score=0.5,
        direction=direction,
        confidence=0.3,
        bullish_events=2,
        bearish_events=0,
        neutral_events=0,
        selected_event_count=2,
        raw_post_count=post_count,
        top_drivers=(),
    )
    return TelegramFlowAssessment(
        as_of=as_of,
        engine_version="telegram-flow-v1",
        source_channels=("Middle_East_Spectator",),
        post_count=post_count,
        event_cluster_count=cluster_count,
        assets=(asset,),
        contributions=(),
        model="gpt-5-mini",
    )


def test_new_posts_always_persist_snapshot() -> None:
    previous = _assessment()
    current = replace(previous, as_of="2026-07-30T10:01:00+00:00")

    should_save, reason = _snapshot_is_informative(current, previous, scored_posts=1)

    assert should_save is True
    assert reason == "new_posts"


def test_unchanged_snapshot_is_skipped_before_heartbeat() -> None:
    previous = _assessment()
    current = replace(previous, as_of="2026-07-30T10:01:00+00:00")

    should_save, reason = _snapshot_is_informative(current, previous, scored_posts=0)

    assert should_save is False
    assert reason == "no_material_change"


def test_snapshot_persists_after_heartbeat() -> None:
    previous = _assessment()
    current = replace(previous, as_of="2026-07-30T10:10:00+00:00")

    should_save, reason = _snapshot_is_informative(current, previous, scored_posts=0)

    assert should_save is True
    assert reason == "heartbeat"


def test_material_score_change_persists_snapshot() -> None:
    previous = _assessment(flow_score=0.25)
    current = _assessment(as_of="2026-07-30T10:01:00+00:00", flow_score=0.28)

    should_save, reason = _snapshot_is_informative(current, previous, scored_posts=0)

    assert should_save is True
    assert reason == "score_changed:Brent"
