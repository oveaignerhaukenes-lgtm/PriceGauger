from __future__ import annotations

from types import SimpleNamespace

import cross_market_runtime
import response_divergence_runtime as runtime
from analysis_status import AnalysisStatusStore
from realtime_market_data import RealtimeBar1m, RealtimeMarketDataStore


NOW = "2026-08-12T12:15:00+00:00"


def _fake_result(status: str):
    return SimpleNamespace(status=status)


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


def _seed_cross_market(path) -> None:
    for market in ("Silver", "Gold", "Brent", "DXY"):
        _bar(path, market=market, stamp="2026-08-12T08:15:00+00:00", price=100.0)
        _bar(path, market=market, stamp="2026-08-12T11:15:00+00:00", price=101.0)
        _bar(path, market=market, stamp="2026-08-12T12:00:00+00:00", price=102.0)
        _bar(path, market=market, stamp=NOW, price=103.0)


def test_response_divergence_runtime_healthy_noop_is_complete(tmp_path, monkeypatch):
    path = tmp_path / "response-runtime.db"

    monkeypatch.setattr(runtime, "refresh_response_divergences", lambda *args, **kwargs: ())

    results = runtime.produce_response_divergences(db_path=path)

    assert results == ()
    status = {item.step_key: item for item in AnalysisStatusStore(path).load()}
    assert status["response_divergence"].status == "COMPLETE"
    assert "Ingen moden" in status["response_divergence"].detail


def test_response_divergence_runtime_reports_persisted_evaluations(tmp_path, monkeypatch):
    path = tmp_path / "response-runtime.db"
    expected = (
        _fake_result("DIVERGENT"),
        _fake_result("ALIGNED"),
        _fake_result("UNCONFIRMED"),
    )
    monkeypatch.setattr(runtime, "refresh_response_divergences", lambda *args, **kwargs: expected)

    results = runtime.produce_response_divergences(db_path=path)

    assert results == expected
    status = {item.step_key: item for item in AnalysisStatusStore(path).load()}
    assert status["response_divergence"].status == "COMPLETE"
    assert "1 divergent" in status["response_divergence"].detail
    assert "1 aligned" in status["response_divergence"].detail
    assert "1 ubekreftet" in status["response_divergence"].detail


def test_response_divergence_runtime_failure_is_degraded(tmp_path, monkeypatch):
    path = tmp_path / "response-runtime.db"

    def fail_refresh(*args, **kwargs):
        raise RuntimeError("synthetic divergence failure")

    monkeypatch.setattr(runtime, "refresh_response_divergences", fail_refresh)

    results = runtime.produce_response_divergences(db_path=path)

    assert results == ()
    status = {item.step_key: item for item in AnalysisStatusStore(path).load()}
    assert status["response_divergence"].status == "FAILED"
    assert "synthetic divergence failure" in status["response_divergence"].detail


def test_cross_market_runtime_hooks_response_divergence_after_snapshot(tmp_path, monkeypatch):
    path = tmp_path / "cross-hook.db"
    _seed_cross_market(path)
    calls: list[str] = []

    def record_response(*, db_path, cross_market, status_store):
        calls.append(cross_market.snapshot_id)
        status_store.complete("response_divergence", "hook called")
        return ()

    monkeypatch.setattr(cross_market_runtime, "produce_response_divergences", record_response)

    snapshot = cross_market_runtime.produce_cross_market_state(db_path=path, as_of=NOW)

    assert snapshot is not None
    assert calls == [snapshot.snapshot_id]
    status = {item.step_key: item for item in AnalysisStatusStore(path).load()}
    assert status["cross_market_state"].status == "COMPLETE"
    assert status["response_divergence"].status == "COMPLETE"
    assert status["response_divergence"].detail == "hook called"
