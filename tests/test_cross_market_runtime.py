from __future__ import annotations

import cross_market_runtime as runtime
import state_runtime_pipeline as pipeline
from analysis_status import AnalysisStatusStore
from cross_market_state import CrossMarketStateStore
from realtime_market_data import RealtimeBar1m, RealtimeMarketDataStore
from telegram_flow_engine import (
    AssetFlowAssessment,
    AssetPostScore,
    ScoredTelegramPost,
    TelegramFlowAssessment,
)


NOW = "2026-08-12T12:00:00+00:00"


def _bar(path, *, market: str, stamp: str, price: float) -> None:
    RealtimeMarketDataStore(path).save_bar(
        RealtimeBar1m(
            market=market,
            bar_time=stamp,
            open=price,
            high=price,
            low=price,
            close=price,
            sample_count=1,
            provider="Saxo OpenAPI",
            uic=123,
            asset_type="ContractFutures",
            symbol="TEST",
        )
    )


def _seed_market(path, market: str) -> None:
    for stamp, price in (
        ("2026-08-12T08:00:00+00:00", 100.0),
        ("2026-08-12T11:00:00+00:00", 101.0),
        ("2026-08-12T11:45:00+00:00", 102.0),
        (NOW, 103.0),
    ):
        _bar(path, market=market, stamp=stamp, price=price)


def _post() -> ScoredTelegramPost:
    return ScoredTelegramPost(
        message_id="runtime-cross-market-1",
        channel="Middle_East_Spectator",
        published_at=NOW,
        text="Material market event",
        event_key="runtime-cross-market",
        relation="new",
        novelty=0.9,
        source_quality=0.8,
        scores=(
            AssetPostScore(
                asset="Silver",
                direction=0.5,
                impact=0.5,
                confidence=0.8,
                horizon_hours=4.0,
                rationale="test",
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
                asset="Silver",
                flow_score=0.2,
                normalized_score=0.5,
                direction="LONG_BIAS",
                confidence=0.5,
                bullish_events=1,
                bearish_events=0,
                neutral_events=0,
                selected_event_count=1,
                raw_post_count=1,
                top_drivers=("test",),
            ),
        ),
        contributions=(),
        model="test-model",
    )


def test_runtime_producer_persists_cross_market_snapshot_and_status(tmp_path):
    path = tmp_path / "cross-runtime.db"
    for market in ("Silver", "Gold", "Brent", "DXY"):
        _seed_market(path, market)

    snapshot = runtime.produce_cross_market_state(db_path=path, as_of=NOW)

    assert snapshot is not None
    persisted = CrossMarketStateStore(path).load_latest(market="Silver")
    assert persisted is not None
    assert persisted.snapshot_id == snapshot.snapshot_id
    status = {item.step_key: item for item in AnalysisStatusStore(path).load()}
    assert status["cross_market_state"].status == "COMPLETE"
    assert "4/4 ferske markeder" in status["cross_market_state"].detail
    assert "12/12 gyldige return-vinduer" in status["cross_market_state"].detail
    assert "3/3 yield-serier mangler" in status["cross_market_state"].detail


def test_runtime_producer_failure_is_degraded_and_visible(tmp_path, monkeypatch):
    path = tmp_path / "cross-runtime.db"

    def fail_build(**kwargs):
        raise RuntimeError("synthetic cross-market failure")

    monkeypatch.setattr(runtime, "build_cross_market_state", fail_build)

    snapshot = runtime.produce_cross_market_state(db_path=path, as_of=NOW)

    assert snapshot is None
    status = {item.step_key: item for item in AnalysisStatusStore(path).load()}
    assert status["cross_market_state"].status == "FAILED"
    assert "synthetic cross-market failure" in status["cross_market_state"].detail


def test_state_runtime_invokes_cross_market_producer_before_other_runtime_work(tmp_path, monkeypatch):
    path = tmp_path / "state-runtime.db"
    calls: list[str] = []

    def record_production(*, db_path, status_store):
        calls.append(str(db_path))
        status_store.complete("cross_market_state", "test producer called")
        return None

    monkeypatch.setattr(pipeline, "produce_cross_market_state", record_production)
    monkeypatch.setenv("PRICEGAUGER_ALERT_MIN_SEVERITY", "CRITICAL")

    pipeline.process_flow_snapshot(
        db_path=path,
        assessment=_assessment(),
        posts=[_post()],
    )

    assert calls == [str(path)]
    status = {item.step_key: item for item in AnalysisStatusStore(path).load()}
    assert status["cross_market_state"].status == "COMPLETE"
    assert status["cross_market_state"].detail == "test producer called"
