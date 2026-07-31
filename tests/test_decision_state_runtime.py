from state_contracts import ComponentStatus, DecisionStateSnapshot, InformationStateSnapshot
from state_runtime_service import build_decision_states, market_impulse_score
from state_runtime_store import StateRuntimeStore
from telegram_flow_engine import AssetFlowAssessment, TelegramFlowAssessment


NOW = "2026-07-30T20:00:00+00:00"


def _information() -> InformationStateSnapshot:
    return InformationStateSnapshot(
        snapshot_id="info-1",
        as_of=NOW,
        event_cluster_count=2,
        active_event_count=2,
        conflict_regime="ACTIVE_WAR",
        ceasefire_active=False,
        narrative_saturation=0.2,
        confirmation_quality=0.5,
        supply_risk=0.4,
        source_channels=("Middle_East_Spectator",),
        component=ComponentStatus(
            observed_at=NOW,
            age_seconds=0,
            freshness="FRESH",
            provider="test",
            instrument="selected-markets",
            engine_version="test-v1",
        ),
    )


def _flow(score: float, direction: str = "LONG_BIAS") -> TelegramFlowAssessment:
    return TelegramFlowAssessment(
        as_of=NOW,
        engine_version="telegram-flow-v1",
        source_channels=("Middle_East_Spectator",),
        post_count=2,
        event_cluster_count=2,
        assets=(
            AssetFlowAssessment(
                asset="Brent",
                flow_score=score,
                normalized_score=score,
                direction=direction,
                confidence=0.4,
                bullish_events=2,
                bearish_events=0,
                neutral_events=0,
                selected_event_count=2,
                raw_post_count=2,
                top_drivers=("driver",),
            ),
        ),
        contributions=(),
        model="test-model",
    )


def test_decision_state_records_change_from_previous():
    previous = DecisionStateSnapshot(
        snapshot_id="previous",
        market="Brent",
        as_of="2026-07-30T19:00:00+00:00",
        previous_snapshot_id="",
        direction="LONG_BIAS",
        direction_score=0.2,
        confidence=0.3,
        expected_move_low_pct=None,
        expected_move_high_pct=None,
        horizon_hours=4.0,
        information_snapshot_id="old-info",
        market_snapshot_id="market-confirmation-pending",
        change_from_previous=0.2,
        contributing_event_ids=(),
        status_reason="test",
    )

    result = build_decision_states(_flow(0.5), _information(), previous={"Brent": previous})[0]
    expected = round(market_impulse_score("Brent", 0.5), 4)

    assert result.direction == "LONG_BIAS"
    assert result.direction_score == expected
    assert result.change_from_previous == round(expected - 0.2, 4)
    assert result.previous_snapshot_id == "previous"
    assert "confirmation pending" in result.status_reason


def test_decision_state_round_trips_through_store(tmp_path):
    store = StateRuntimeStore(tmp_path / "state.sqlite3")
    decision = build_decision_states(_flow(0.5), _information())[0]
    expected = round(market_impulse_score("Brent", 0.5), 4)

    assert store.save_decision_states([decision]) == 1
    loaded = store.load_latest_decision_state(market="Brent")
    latest = store.load_latest_decision_states()

    assert loaded is not None
    assert loaded.snapshot_id == decision.snapshot_id
    assert loaded.market == "Brent"
    assert len(latest) == 1
    assert latest[0].direction_score == expected
