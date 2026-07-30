from state_contracts import MarketMoverAlert
from state_runtime_store import StateRuntimeStore
from telegram_flow_engine import AssetFlowAssessment, TelegramFlowAssessment
from telegram_flow_store import TelegramFlowStore
from overview_service import load_overview


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


def test_overview_handles_empty_database(tmp_path):
    result = load_overview(tmp_path / "empty.sqlite3")

    assert result.flow is None
    assert result.markets == ()
    assert result.latest_posts == ()
    assert result.latest_alert is None
