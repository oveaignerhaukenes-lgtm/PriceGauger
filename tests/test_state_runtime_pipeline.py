from datetime import datetime, timezone

from analysis_status import AnalysisStatusStore
from database import connect
import state_runtime_pipeline as pipeline
from state_runtime_pipeline import process_flow_snapshot
from state_runtime_store import StateRuntimeStore
from market_interpretation import MarketInterpretation
from market_state_store import MarketStateStore
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


def _interpretation(event_id: str, *, update_type: str, conflict: float, supply: float) -> MarketInterpretation:
    return MarketInterpretation.from_mapping(
        {
            "event_id": event_id,
            "cluster_id": "iran-conflict",
            "published_at": NOW,
            "summary": "Material update in the Iran conflict",
            "state_deltas": {
                "conflict_pressure": conflict,
                "energy_supply_risk": supply,
                "shipping_risk": supply,
                "safe_haven_pressure": max(0.0, conflict),
                "usd_pressure": 0.0,
            },
            "novelty": 1.0,
            "confidence": 1.0,
            "source_quality": 1.0,
            "update_type": update_type,
        }
    )


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


def test_missing_technical_market_state_is_bootstrapped_without_new_post(tmp_path, monkeypatch):
    monkeypatch.setenv("PRICEGAUGER_ALERT_MIN_SEVERITY", "CRITICAL")
    db_path = tmp_path / "state.sqlite3"

    process_flow_snapshot(db_path=db_path, assessment=_assessment(), posts=[_post()])
    first_counts = _counts(db_path)

    class ConfiguredSaxo:
        client = object()
        instruments = {"Brent": object()}

    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(pipeline, "SaxoPriceProvider", ConfiguredSaxo)

    def build_states(markets, *, fetcher):
        calls.append(tuple(markets))
        return {}, {market: "test feed unavailable" for market in markets}

    monkeypatch.setattr(pipeline, "build_technical_market_states", build_states)

    process_flow_snapshot(db_path=db_path, assessment=_assessment(), posts=[_post()])

    assert calls == [("Brent",)]
    assert _counts(db_path) == (first_counts[0] + 1, first_counts[1] + 1)


def test_technical_status_is_not_left_pending_when_saxo_has_no_instruments(tmp_path, monkeypatch):
    monkeypatch.setenv("PRICEGAUGER_ALERT_MIN_SEVERITY", "CRITICAL")
    db_path = tmp_path / "state.sqlite3"

    class ConnectedSaxoWithoutInstruments:
        client = object()
        instruments = {}

    monkeypatch.setattr(pipeline, "SaxoPriceProvider", ConnectedSaxoWithoutInstruments)
    process_flow_snapshot(db_path=db_path, assessment=_assessment(), posts=[_post()])

    technical = next(
        item for item in AnalysisStatusStore(db_path).load() if item.step_key == "technical_state"
    )
    assert technical.status == "SKIPPED"
    assert "SAXO_INSTRUMENTS_JSON" in technical.detail


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


def test_information_state_updates_previous_snapshot_once_per_interpretation(tmp_path, monkeypatch):
    monkeypatch.setenv("PRICEGAUGER_ALERT_MIN_SEVERITY", "CRITICAL")
    db_path = tmp_path / "state.sqlite3"
    real_builder = pipeline.build_information_state
    build_time = [datetime.fromisoformat(NOW)]
    monkeypatch.setattr(
        pipeline,
        "build_information_state",
        lambda flow, interpretations, **kwargs: real_builder(
            flow, interpretations, as_of=build_time[0], **kwargs
        ),
    )
    interpretation_store = MarketStateStore(db_path)
    interpretation_store.save_interpretation(
        _interpretation("event-1", update_type="ESCALATION", conflict=0.6, supply=0.5)
    )

    process_flow_snapshot(db_path=db_path, assessment=_assessment(), posts=[_post()])
    first = StateRuntimeStore(db_path).load_latest_information_snapshot()
    assert first is not None
    assert first.state_values["conflict_pressure"] == 0.6
    assert first.processed_event_ids == ("event-1",)

    monkeypatch.setattr(pipeline, "_heartbeat_due", lambda latest: True)
    process_flow_snapshot(db_path=db_path, assessment=_assessment(), posts=[_post()])
    heartbeat = StateRuntimeStore(db_path).load_latest_information_snapshot()
    assert heartbeat is not None
    assert heartbeat.state_values["conflict_pressure"] == 0.6

    interpretation_store.save_interpretation(
        _interpretation("event-2", update_type="DEESCALATION", conflict=-0.25, supply=-0.2)
    )
    build_time[0] = datetime.fromisoformat(NOW).replace(minute=1)
    process_flow_snapshot(db_path=db_path, assessment=_assessment(), posts=[_post()])
    updated = StateRuntimeStore(db_path).load_latest_information_snapshot()
    assert updated is not None
    assert updated.state_values["conflict_pressure"] < 0.36
    assert updated.state_change["conflict_pressure"] < -0.24
    assert updated.processed_event_ids == ("event-1", "event-2")


def test_context_and_duplicate_are_recorded_but_do_not_change_information_state(tmp_path, monkeypatch):
    monkeypatch.setenv("PRICEGAUGER_ALERT_MIN_SEVERITY", "CRITICAL")
    db_path = tmp_path / "state.sqlite3"
    real_builder = pipeline.build_information_state
    monkeypatch.setattr(
        pipeline,
        "build_information_state",
        lambda flow, interpretations, **kwargs: real_builder(
            flow, interpretations, as_of=datetime.fromisoformat(NOW), **kwargs
        ),
    )
    store = MarketStateStore(db_path)
    store.save_interpretation(_interpretation("context-1", update_type="CONTEXT", conflict=1.0, supply=1.0))
    store.save_interpretation(_interpretation("duplicate-1", update_type="DUPLICATE", conflict=1.0, supply=1.0))

    process_flow_snapshot(db_path=db_path, assessment=_assessment(), posts=[_post()])
    information = StateRuntimeStore(db_path).load_latest_information_snapshot()

    assert information is not None
    assert information.state_values["conflict_pressure"] == 0.0
    assert information.active_event_count == 0
    assert set(information.processed_event_ids) == {"context-1", "duplicate-1"}
