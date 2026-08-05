from state_contracts import (
    ComponentStatus,
    EventContribution,
    InformationStateSnapshot,
    MarketStateSnapshot,
    context_multiplier,
    detect_market_mover,
)
from state_runtime_service import contributions_from_posts
from telegram_flow_engine import AssetPostScore, ScoredTelegramPost


NOW = "2026-07-30T20:00:00+00:00"


def _component() -> ComponentStatus:
    return ComponentStatus(
        observed_at=NOW,
        age_seconds=0,
        freshness="FRESH",
        provider="test",
        instrument="Brent continuous_front_month",
        engine_version="test-v1",
    )


def _information(*, ceasefire: bool, regime: str, saturation: float) -> InformationStateSnapshot:
    return InformationStateSnapshot(
        snapshot_id="info-1",
        as_of=NOW,
        event_cluster_count=4,
        active_event_count=2,
        conflict_regime=regime,
        ceasefire_active=ceasefire,
        narrative_saturation=saturation,
        confirmation_quality=0.7,
        supply_risk=0.5,
        source_channels=("Middle_East_Spectator",),
        component=_component(),
    )


def _market(price_confirmation: float = 0.0) -> MarketStateSnapshot:
    return MarketStateSnapshot(
        snapshot_id="market-1",
        market="Brent",
        as_of=NOW,
        price=88.0,
        direction_score=0.1,
        volatility_score=0.4,
        momentum_score=0.1,
        price_confirmation=price_confirmation,
        regime="NORMAL",
        component=_component(),
    )


def _contribution(*, move: float, nudge: float, quality: float = 0.7) -> EventContribution:
    return EventContribution(
        event_id="MES:1",
        event_cluster_id="iran-bombing",
        market="Brent",
        observed_at=NOW,
        direction_nudge=nudge,
        confidence_nudge=0.4,
        expected_move_low_pct=move / 2,
        expected_move_high_pct=move,
        horizon_hours=4.0,
        novelty=0.9,
        source_quality=quality,
        confirmation_status="UNCONFIRMED",
        rationale="Potential escalation affecting supply risk.",
    )


def test_ceasefire_context_makes_same_report_more_significant_than_active_war():
    ceasefire = _information(ceasefire=True, regime="CEASEFIRE", saturation=0.1)
    active_war = _information(ceasefire=False, regime="ACTIVE_WAR", saturation=0.8)

    assert context_multiplier(ceasefire) > context_multiplier(active_war)


def test_small_low_novelty_report_does_not_create_market_mover():
    contribution = EventContribution(
        event_id="MES:2",
        event_cluster_id="routine-update",
        market="Brent",
        observed_at=NOW,
        direction_nudge=0.1,
        confidence_nudge=0.05,
        expected_move_low_pct=0.05,
        expected_move_high_pct=0.2,
        horizon_hours=1.0,
        novelty=0.2,
        source_quality=0.5,
        confirmation_status="UNCONFIRMED",
        rationale="Routine update.",
    )

    alert = detect_market_mover(
        contribution,
        _information(ceasefire=False, regime="ACTIVE_WAR", saturation=0.8),
        _market(),
        headline="Routine update",
        summary="No material change.",
    )

    assert alert is None


def test_large_ceasefire_break_report_creates_critical_alert():
    alert = detect_market_mover(
        _contribution(move=5.0, nudge=0.9, quality=0.75),
        _information(ceasefire=True, regime="CEASEFIRE", saturation=0.05),
        _market(),
        headline="Massive bombing reported in Iran",
        summary="Unconfirmed report during an active ceasefire.",
    )

    assert alert is not None
    assert alert.severity == "CRITICAL"
    assert alert.status == "ACTIVE"
    assert alert.expected_direction == "UP"
    assert alert.context_multiplier > 1.0


def test_price_confirmation_updates_alert_status():
    alert = detect_market_mover(
        _contribution(move=2.5, nudge=0.7),
        _information(ceasefire=False, regime="DEESCALATING", saturation=0.2),
        _market(price_confirmation=0.5),
        headline="New supply disruption",
        summary="Price response confirms the initial interpretation.",
    )

    assert alert is not None
    assert alert.status == "CONFIRMED"


def test_contribution_uses_explicit_fallback_when_post_timestamp_is_blank():
    post = ScoredTelegramPost(
        message_id="MES:missing-time",
        channel="Middle_East_Spectator",
        published_at="",
        text="Material update",
        event_key="material-update",
        relation="new",
        novelty=0.8,
        source_quality=0.8,
        scores=(
            AssetPostScore(
                asset="Brent",
                direction=-1.0,
                impact=0.7,
                confidence=0.8,
                horizon_hours=24.0,
                rationale="Test fallback timestamp.",
            ),
        ),
    )

    contribution = contributions_from_posts(
        [post], fallback_observed_at=NOW
    )[0]

    assert contribution.observed_at == NOW
