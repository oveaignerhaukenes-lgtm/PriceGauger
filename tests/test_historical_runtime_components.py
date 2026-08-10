from datetime import datetime, timezone

from analysis_view_preferences import ENGINE_HISTORICAL, ENGINE_NEWS_CONTEXT, ENGINE_TECHNICAL
from decision_engine_components import (
    DecisionEngineComponentStore,
    apply_historical_confirmation,
    projected_direction,
    projected_score,
)
from historical_engine import build_historical_assessment
from historical_signal_store import HistoricalRuntimeSignalStore, signal_from_assessment
from state_contracts import ComponentStatus, DecisionStateSnapshot, MarketStateSnapshot


def _decision(score: float = 0.4) -> DecisionStateSnapshot:
    return DecisionStateSnapshot(
        snapshot_id="decision:base",
        market="Brent",
        as_of=datetime(2026, 8, 10, tzinfo=timezone.utc).isoformat(),
        previous_snapshot_id="",
        direction="LONG_BIAS",
        direction_score=score,
        confidence=0.7,
        expected_move_low_pct=None,
        expected_move_high_pct=None,
        horizon_hours=4.0,
        information_snapshot_id="info:1",
        market_snapshot_id="market:1",
        change_from_previous=0.1,
        contributing_event_ids=("tabzlive:123",),
        status_reason="base",
    )


def _market(score: float = 0.2) -> MarketStateSnapshot:
    return MarketStateSnapshot(
        snapshot_id="market:1",
        market="Brent",
        as_of=datetime(2026, 8, 10, tzinfo=timezone.utc).isoformat(),
        price=84.0,
        direction_score=score,
        volatility_score=0.4,
        momentum_score=0.2,
        price_confirmation=0.2,
        regime="TREND",
        component=ComponentStatus(
            observed_at=datetime(2026, 8, 10, tzinfo=timezone.utc).isoformat(),
            age_seconds=0,
            freshness="FRESH",
            provider="test",
            instrument="Brent",
            engine_version="test",
        ),
    )


def _historical_signal():
    assessment = build_historical_assessment(
        [
            {"candidate_event_id": str(i), "published_at": f"2026-07-{i + 1:02d}T00:00:00+00:00", "status": "OK", "return_4h_pct": value}
            for i, value in enumerate((1.0, 1.5, 0.5, 2.0, 1.2, -0.3))
        ],
        source_search_id="search:1",
        asset="Brent",
        semantic_filter_applied=True,
    )
    return signal_from_assessment(assessment, event_id="tabzlive:123")


def test_without_historical_signal_preserves_authoritative_decision() -> None:
    decision = _decision()
    adjusted, components = apply_historical_confirmation(
        decision,
        market_state=_market(),
        historical=None,
    )

    assert adjusted == decision
    assert components.weights[ENGINE_NEWS_CONTEXT] == 0.72
    assert components.weights[ENGINE_TECHNICAL] == 0.28
    assert ENGINE_HISTORICAL not in components.available_engines


def test_matching_historical_signal_gets_conservative_weight() -> None:
    decision = _decision()
    signal = _historical_signal()
    adjusted, components = apply_historical_confirmation(
        decision,
        market_state=_market(),
        historical=signal,
    )

    assert adjusted.snapshot_id != decision.snapshot_id
    assert components.weights[ENGINE_HISTORICAL] == 0.15
    assert components.historical_assessment_id == signal.assessment_id
    assert adjusted.direction_score != decision.direction_score


def test_projection_renormalizes_only_selected_available_engines() -> None:
    _, components = apply_historical_confirmation(
        _decision(),
        market_state=_market(),
        historical=_historical_signal(),
    )

    information_only = projected_score(components, (ENGINE_NEWS_CONTEXT,))
    technical_only = projected_score(components, (ENGINE_TECHNICAL,))
    combined = projected_score(components, (ENGINE_NEWS_CONTEXT, ENGINE_TECHNICAL))

    assert information_only == components.scores[ENGINE_NEWS_CONTEXT]
    assert technical_only == components.scores[ENGINE_TECHNICAL]
    assert combined is not None
    assert projected_direction(information_only) in {"LONG_BIAS", "SHORT_BIAS", "NEUTRAL"}
    assert projected_score(components, ()) is None


def test_signal_and_component_stores_are_event_and_market_scoped(tmp_path) -> None:
    db = tmp_path / "pg.db"
    signal_store = HistoricalRuntimeSignalStore(db)
    signal = _historical_signal()
    signal_store.save(signal)

    assert signal_store.load_latest_for_events(market="Brent", event_ids=("tabzlive:123",)) == signal
    assert signal_store.load_latest_for_events(market="Brent", event_ids=("other:123",)) is None
    assert signal_store.load_latest_for_events(market="Gold", event_ids=("tabzlive:123",)) is None

    adjusted, components = apply_historical_confirmation(_decision(), market_state=_market(), historical=signal)
    store = DecisionEngineComponentStore(db)
    store.save_all([components])
    assert store.load_latest(market="Brent") == components
    assert adjusted.snapshot_id == components.decision_snapshot_id
