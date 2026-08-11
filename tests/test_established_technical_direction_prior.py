from datetime import datetime, timezone

from analysis_view_preferences import ENGINE_HISTORICAL, ENGINE_NEWS_CONTEXT, ENGINE_TECHNICAL
from decision_engine_components import (
    ESTABLISHED_TECHNICAL_WEIGHT,
    HISTORICAL_WEIGHT,
    TECHNICAL_DIRECTION_PRIOR_VERSION,
    apply_historical_confirmation,
)
from historical_signal_store import HistoricalRuntimeSignal
from state_contracts import ComponentStatus, DecisionStateSnapshot, MarketStateSnapshot


NOW = datetime(2026, 8, 11, 7, 0, tzinfo=timezone.utc).isoformat()


def _decision(*, information: float, technical: float) -> DecisionStateSnapshot:
    # Runtime Decision State already contains the normal 72/28 information/technical blend.
    score = 0.72 * information + 0.28 * technical
    return DecisionStateSnapshot(
        snapshot_id="decision:base",
        market="Brent",
        as_of=NOW,
        previous_snapshot_id="",
        direction="LONG_BIAS" if score > 0.10 else "SHORT_BIAS" if score < -0.10 else "NEUTRAL",
        direction_score=score,
        confidence=0.55,
        expected_move_low_pct=None,
        expected_move_high_pct=None,
        horizon_hours=4.0,
        information_snapshot_id="info:1",
        market_snapshot_id="market:1",
        change_from_previous=0.0,
        contributing_event_ids=("event:1",),
        status_reason="base",
    )


def _market(score: float, *, freshness: str = "FRESH") -> MarketStateSnapshot:
    return MarketStateSnapshot(
        snapshot_id="market:1",
        market="Brent",
        as_of=NOW,
        price=88.0,
        direction_score=score,
        volatility_score=0.4,
        momentum_score=score,
        price_confirmation=score,
        regime="TREND",
        component=ComponentStatus(
            observed_at=NOW,
            age_seconds=0,
            freshness=freshness,
            provider="test",
            instrument="Brent",
            engine_version="test",
        ),
    )


def _historical() -> HistoricalRuntimeSignal:
    return HistoricalRuntimeSignal(
        assessment_id="historical:1",
        event_id="event:1",
        market="Brent",
        as_of=NOW,
        direction_score=0.2,
        confidence=0.5,
        expected_return_pct=0.2,
        interval_low_pct=-0.2,
        interval_high_pct=0.5,
        independent_analogues=8,
        status="READY",
    )


def test_established_opposing_technical_trend_can_turn_new_decision_short() -> None:
    decision = _decision(information=1.0, technical=-0.75)
    assert decision.direction == "LONG_BIAS"

    adjusted, components = apply_historical_confirmation(
        decision,
        market_state=_market(-0.75),
        historical=None,
    )

    assert adjusted.snapshot_id != decision.snapshot_id
    assert adjusted.direction == "SHORT_BIAS"
    assert adjusted.direction_score < -0.10
    assert components.weights[ENGINE_TECHNICAL] == ESTABLISHED_TECHNICAL_WEIGHT
    assert components.weights[ENGINE_NEWS_CONTEXT] == round(1.0 - ESTABLISHED_TECHNICAL_WEIGHT, 6)
    assert TECHNICAL_DIRECTION_PRIOR_VERSION in adjusted.status_reason
    assert components.decision_snapshot_id == adjusted.snapshot_id


def test_slight_technical_conflict_keeps_normal_72_28_blend() -> None:
    decision = _decision(information=1.0, technical=-0.45)

    adjusted, components = apply_historical_confirmation(
        decision,
        market_state=_market(-0.45),
        historical=None,
    )

    assert adjusted == decision
    assert components.weights[ENGINE_NEWS_CONTEXT] == 0.72
    assert components.weights[ENGINE_TECHNICAL] == 0.28


def test_stale_strong_technical_state_cannot_take_control() -> None:
    decision = _decision(information=1.0, technical=-0.75)

    adjusted, components = apply_historical_confirmation(
        decision,
        market_state=_market(-0.75, freshness="STALE"),
        historical=None,
    )

    assert adjusted == decision
    assert ENGINE_TECHNICAL not in components.available_engines
    assert components.weights[ENGINE_NEWS_CONTEXT] == 1.0
    assert components.weights[ENGINE_TECHNICAL] == 0.0


def test_aligned_established_technical_state_does_not_invoke_conflict_prior() -> None:
    decision = _decision(information=0.8, technical=0.75)

    adjusted, components = apply_historical_confirmation(
        decision,
        market_state=_market(0.75),
        historical=None,
    )

    assert adjusted == decision
    assert components.weights[ENGINE_NEWS_CONTEXT] == 0.72
    assert components.weights[ENGINE_TECHNICAL] == 0.28
    assert TECHNICAL_DIRECTION_PRIOR_VERSION not in adjusted.status_reason


def test_historical_weight_is_preserved_when_technical_prior_is_active() -> None:
    decision = _decision(information=1.0, technical=-0.75)

    adjusted, components = apply_historical_confirmation(
        decision,
        market_state=_market(-0.75),
        historical=_historical(),
    )

    assert components.weights[ENGINE_HISTORICAL] == HISTORICAL_WEIGHT
    assert components.weights[ENGINE_TECHNICAL] == round(ESTABLISHED_TECHNICAL_WEIGHT * (1.0 - HISTORICAL_WEIGHT), 6)
    assert components.weights[ENGINE_NEWS_CONTEXT] == round((1.0 - ESTABLISHED_TECHNICAL_WEIGHT) * (1.0 - HISTORICAL_WEIGHT), 6)
    assert abs(sum(components.weights.values()) - 1.0) < 1e-9
    assert adjusted.direction == "SHORT_BIAS"
