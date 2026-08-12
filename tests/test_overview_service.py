from forecast_contracts import forecast_from_decision
from forecast_store import ForecastStore
from overview_service import load_overview, load_overview_markets
from state_contracts import ComponentStatus, DecisionStateSnapshot, MarketMoverAlert, MarketStateSnapshot
from state_runtime_store import StateRuntimeStore
from telegram_flow_engine import AssetFlowAssessment, TelegramFlowAssessment
from telegram_flow_store import TelegramFlowStore


NOW = "2026-07-30T20:00:00+00:00"


def _flow() -> TelegramFlowAssessment:
    return TelegramFlowAssessment(
        as_of=NOW,
        engine_version="telegram-flow-v1",
        source_channels=("Middle_East_Spectator",),
        post_count=3,
        event_cluster_count=2,
        assets=(
            AssetFlowAssessment(
                asset="Brent",
                flow_score=0.25,
                normalized_score=0.5,
                direction="LONG_BIAS",
                confidence=0.4,
                bullish_events=2,
                bearish_events=0,
                neutral_events=0,
                selected_event_count=2,
                raw_post_count=3,
                top_drivers=("+0.20 · MES · supply risk",),
            ),
        ),
        contributions=(),
        model="test-model",
    )


def _alert() -> MarketMoverAlert:
    return MarketMoverAlert(
        alert_id="alert-1",
        event_cluster_id="cluster-1",
        created_at=NOW,
        updated_at=NOW,
        status="ACTIVE",
        severity="ALERT",
        headline="Supply disruption",
        summary="Potential short-term Brent move.",
        confirmation_status="UNCONFIRMED",
        source_quality=0.7,
        novelty=0.8,
        market="Brent",
        expected_direction="UP",
        expected_move_low_pct=1.0,
        expected_move_high_pct=2.0,
        horizon_hours=4.0,
        state_delta=0.6,
        price_confirmation=0.0,
        context_multiplier=1.2,
        rationale="test",
    )


def _decision() -> DecisionStateSnapshot:
    return DecisionStateSnapshot(
        snapshot_id="decision:brent:overview",
        market="Brent",
        as_of=NOW,
        previous_snapshot_id="",
        direction="LONG_BIAS",
        direction_score=0.64,
        confidence=0.71,
        expected_move_low_pct=0.6,
        expected_move_high_pct=1.4,
        horizon_hours=4.0,
        information_snapshot_id="information:overview",
        market_snapshot_id="market:brent:overview",
        change_from_previous=0.12,
        contributing_event_ids=("event-1",),
        status_reason="test state",
    )


def _market_state() -> MarketStateSnapshot:
    return MarketStateSnapshot(
        snapshot_id="market:brent:overview",
        market="Brent",
        as_of=NOW,
        price=80.0,
        direction_score=0.4,
        volatility_score=0.3,
        momentum_score=0.5,
        price_confirmation=0.4,
        regime="UPTREND",
        component=ComponentStatus(
            observed_at=NOW,
            age_seconds=0,
            freshness="FRESH",
            provider="test",
            instrument="Brent",
            engine_version="technical-v1",
        ),
    )


def test_overview_reads_flow_and_alert_from_same_database(tmp_path):
    db_path = tmp_path / "overview.sqlite3"
    TelegramFlowStore(db_path).save_snapshot(_flow())
    StateRuntimeStore(db_path).save_alert(_alert())

    result = load_overview(db_path)

    assert result.flow is not None
    assert result.flow.model == "test-model"
    assert len(result.markets) == 1
    assert result.markets[0].market == "Brent"
    assert result.markets[0].direction == "LONG_BIAS"
    assert result.latest_alert is not None
    assert result.latest_alert.alert_id == "alert-1"


def test_live_overview_can_select_one_hour_family_without_changing_default_overview(tmp_path):
    db_path = tmp_path / "horizon.sqlite3"
    runtime = StateRuntimeStore(db_path)
    decision = _decision()
    market_state = _market_state()
    runtime.save_decision_states((decision,))
    runtime.save_market_states((market_state,))

    forecasts = (
        forecast_from_decision(decision, market_state=market_state, horizon_hours=1.0),
        forecast_from_decision(decision, market_state=market_state, horizon_hours=4.0),
    )
    ForecastStore(db_path).save_all(forecasts)

    selected = load_overview_markets(db_path, horizons_by_market={"Brent": 1.0})[0]
    default = load_overview(db_path).markets[0]

    assert selected.forecast is not None
    assert selected.forecast.horizon_hours == 1.0
    assert selected.horizon_hours == 1.0
    assert selected.expected_move_low_pct == 0.3
    assert selected.expected_move_high_pct == 0.7
    assert all(item.horizon_hours == 1.0 for item in selected.forecasts)

    assert default.forecast is not None
    assert default.forecast.horizon_hours == 4.0
    assert default.horizon_hours == 4.0
    assert default.expected_move_low_pct == 0.6
    assert default.expected_move_high_pct == 1.4


def test_overview_handles_empty_database(tmp_path):
    result = load_overview(tmp_path / "empty.sqlite3")

    assert result.flow is None
    assert result.markets == ()
    assert result.latest_posts == ()
    assert result.latest_alert is None
