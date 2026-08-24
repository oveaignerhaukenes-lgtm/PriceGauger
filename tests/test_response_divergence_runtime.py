from __future__ import annotations

from types import SimpleNamespace

import response_divergence_runtime as runtime
from analysis_status import AnalysisStatusStore


def _fake_result(status: str):
    return SimpleNamespace(status=status)


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
