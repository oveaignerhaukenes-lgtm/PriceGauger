from state_contracts import ComponentStatus, DecisionStateSnapshot, InformationStateSnapshot, MarketStateSnapshot
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
        state_values={
            "conflict_pressure": 0.5,
            "energy_supply_risk": 0.8,
            "shipping_risk": 0.6,
            "safe_haven_pressure": 0.2,
            "usd_pressure": 0.0,
        },
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
    state_score = 0.20 * 0.5 + 0.50 * 0.8 + 0.35 * 0.6
    expected = round(0.65 * state_score + 0.35 * market_impulse_score("Brent", 0.5), 4)

    assert result.direction == "LONG_BIAS"
    assert result.direction_score == expected
    assert result.change_from_previous == round(expected - 0.2, 4)
    assert result.previous_snapshot_id == "previous"
    assert "confirmation pending" in result.status_reason


def test_decision_state_round_trips_through_store(tmp_path):
    store = StateRuntimeStore(tmp_path / "state.sqlite3")
    decision = build_decision_states(_flow(0.5), _information())[0]
    state_score = 0.20 * 0.5 + 0.50 * 0.8 + 0.35 * 0.6
    expected = round(0.65 * state_score + 0.35 * market_impulse_score("Brent", 0.5), 4)

    assert store.save_decision_states([decision]) == 1
    loaded = store.load_latest_decision_state(market="Brent")
    latest = store.load_latest_decision_states()

    assert loaded is not None
    assert loaded.snapshot_id == decision.snapshot_id
    assert loaded.market == "Brent"
    assert len(latest) == 1
    assert latest[0].direction_score == expected


def test_decision_state_combines_persistent_information_with_latest_flow():
    result = build_decision_states(_flow(-0.05, direction="SHORT_BIAS"), _information())[0]

    assert result.direction == "LONG_BIAS"
    assert result.direction_score > 0.2
    assert "Persistent Information State" in result.status_reason


def test_decision_state_adds_fresh_technical_confirmation():
    market = MarketStateSnapshot(
        snapshot_id="market-1",
        market="Brent",
        as_of=NOW,
        price=88.0,
        direction_score=0.8,
        volatility_score=0.4,
        momentum_score=0.8,
        price_confirmation=0.8,
        regime="BULLISH · HIGH",
        component=ComponentStatus(NOW, 0, "FRESH", "Saxo OpenAPI", "Brent", "technical-v1"),
    )

    without = build_decision_states(_flow(0.5), _information())[0]
    confirmed = build_decision_states(_flow(0.5), _information(), market_states={"Brent": market})[0]

    assert confirmed.market_snapshot_id == "market-1"
    assert confirmed.direction_score > 0
    assert confirmed.snapshot_id != without.snapshot_id
    assert confirmed.confidence > without.confidence
    assert "Technical confirmation" in confirmed.status_reason
