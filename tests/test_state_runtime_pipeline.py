from datetime import datetime, timezone

from database import connect
import state_runtime_pipeline as pipeline
from state_runtime_pipeline import process_flow_snapshot
from state_runtime_store import StateRuntimeStore
from telegram_flow_engine import (
    AssetFlowAssessment,
    AssetPostScore,
    ScoredTelegramPost,
    TelegramFlowAssessment,
)


NOW = "2026-07-30T20:00:00+00:00"


def _post() -> ScoredTelegramPost:
    return ScoredTelegramPost(
        message_id="9001",
        channel="Middle_East_Spectator",
        published_at=NOW,
        text="Massive bombing reported in Iran",
        event_key="iran-major-bombing",
        relation="new",
        novelty=0.95,
        source_quality=0.8,
        scores=(
            AssetPostScore(
                asset="Brent",
                direction=1.0,
                impact=1.0,
                confidence=0.9,
                horizon_hours=4.0,
                rationale="Potential escalation and supply-risk shock.",
            ),
        ),
    )


def _assessment() -> TelegramFlowAssessment:
    return TelegramFlowAssessment(
        as_of=NOW,
        engine_version="telegram-flow-v1",
        source_channels=("Middle_East_Spectator",),
        post_count=1,
        event_cluster_count=1,
        assets=(
            AssetFlowAssessment(
                asset="Brent",
                flow_score=0.68,
                normalized_score=1.0,
                direction="LONG_BIAS",
                confidence=0.25,
                bullish_events=1,
                bearish_events=0,
                neutral_events=0,
                selected_event_count=1,
                raw_post_count=1,
                top_drivers=("major bombing",),
            ),
        ),
        contributions=(),
        model="test-model",
    )


def _counts(db_path) -> tuple[int, int]:
    with connect(db_path) as db:
        information = db.execute("SELECT COUNT(*) AS count FROM information_state_snapshots").fetchone()["count"]
        decisions = db.execute("SELECT COUNT(*) AS count FROM decision_state_snapshots").fetchone()["count"]
    return int(information), int(decisions)


def test_flow_snapshot_persists_information_contributions_and_alert(tmp_path, monkeypatch):
    monkeypatch.setenv("PRICEGAUGER_ALERT_MIN_SEVERITY", "CRITICAL")
    db_path = tmp_path / "state.sqlite3"

    process_flow_snapshot(db_path=db_path, assessment=_assessment(), posts=[_post()])

    store = StateRuntimeStore(db_path)
    information = store.load_latest_information_state()
    alert = store.load_latest_alert(market="Brent")

    assert information is not None
    assert information["event_cluster_count"] == 1
    assert store.has_contribution(event_id="9001", market="Brent") is True
    assert alert is not None
    assert alert.market == "Brent"
    assert alert.expected_direction == "UP"


def test_same_post_is_not_reprocessed_or_persisted_each_cycle(tmp_path, monkeypatch):
    monkeypatch.setenv("PRICEGAUGER_ALERT_MIN_SEVERITY", "CRITICAL")
    db_path = tmp_path / "state.sqlite3"

    process_flow_snapshot(db_path=db_path, assessment=_assessment(), posts=[_post()])
    first = StateRuntimeStore(db_path).load_latest_alert(market="Brent")
    first_counts = _counts(db_path)

    process_flow_snapshot(db_path=db_path, assessment=_assessment(), posts=[_post()])
    second = StateRuntimeStore(db_path).load_latest_alert(market="Brent")

    assert first is not None
    assert second is not None
    assert first.alert_id == second.alert_id
    assert _counts(db_path) == first_counts


def test_missing_decision_state_is_bootstrapped_without_new_post(tmp_path, monkeypatch):
    monkeypatch.setenv("PRICEGAUGER_ALERT_MIN_SEVERITY", "CRITICAL")
    db_path = tmp_path / "state.sqlite3"

    process_flow_snapshot(db_path=db_path, assessment=_assessment(), posts=[_post()])
    with connect(db_path) as db:
        db.execute("DELETE FROM decision_state_snapshots")

    assert StateRuntimeStore(db_path).load_latest_decision_state(market="Brent") is None

    process_flow_snapshot(db_path=db_path, assessment=_assessment(), posts=[_post()])

    decision = StateRuntimeStore(db_path).load_latest_decision_state(market="Brent")
    assert decision is not None
    assert decision.direction == "LONG_BIAS"


def test_heartbeat_persists_state_without_reprocessing_posts(tmp_path, monkeypatch):
    monkeypatch.setenv("PRICEGAUGER_ALERT_MIN_SEVERITY", "CRITICAL")
    db_path = tmp_path / "state.sqlite3"

    process_flow_snapshot(db_path=db_path, assessment=_assessment(), posts=[_post()])
    first_counts = _counts(db_path)
    monkeypatch.setattr(pipeline, "_heartbeat_due", lambda latest: True)

    process_flow_snapshot(db_path=db_path, assessment=_assessment(), posts=[_post()])
    second_counts = _counts(db_path)

    assert second_counts[0] == first_counts[0] + 1
    assert second_counts[1] == first_counts[1] + 1
