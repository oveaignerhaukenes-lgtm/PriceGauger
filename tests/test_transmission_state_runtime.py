from __future__ import annotations

import response_divergence_runtime
import transmission_state_runtime as runtime
from analysis_status import AnalysisStatusStore
from response_divergence import ResponseDivergenceSnapshot
from transmission_state import TransmissionStateStore


AS_OF = "2026-08-12T12:15:00+00:00"


def _divergence() -> ResponseDivergenceSnapshot:
    supporting = {
        "Silver": {"kind": "RETURN_PCT", "change": -1.0, "window_coverage": "VALID", "latest_observation_freshness": "FRESH"},
        "Gold": {"kind": "RETURN_PCT", "change": 0.5, "window_coverage": "VALID", "latest_observation_freshness": "FRESH"},
        "Brent": {"kind": "RETURN_PCT", "change": 0.01, "window_coverage": "VALID", "latest_observation_freshness": "FRESH"},
        "DXY": {"kind": "RETURN_PCT", "change": 0.4, "window_coverage": "VALID", "latest_observation_freshness": "FRESH"},
        "US2Y": {"kind": "YIELD_PCT", "change": 0.08, "window_coverage": "VALID", "latest_observation_freshness": "FRESH"},
        "US10Y": {"kind": "YIELD_PCT", "change": 0.10, "window_coverage": "VALID", "latest_observation_freshness": "FRESH"},
        "US30Y": {"kind": "YIELD_PCT", "change": 0.12, "window_coverage": "VALID", "latest_observation_freshness": "FRESH"},
    }
    return ResponseDivergenceSnapshot(
        divergence_id="divergence:runtime",
        market="Silver",
        window="15m",
        as_of=AS_OF,
        information_snapshot_id="information:runtime",
        information_as_of="2026-08-12T12:00:00+00:00",
        cross_market_snapshot_id="cross:runtime",
        cross_market_as_of=AS_OF,
        expected_score=0.4,
        expected_direction="UP",
        realized_return_pct=-1.0,
        realized_direction="DOWN",
        status="DIVERGENT",
        alignment_offset_seconds=0.0,
        supporting_observations=supporting,
    )


def test_transmission_runtime_healthy_noop_is_complete(tmp_path):
    path = tmp_path / "transmission-runtime.db"

    results = runtime.produce_transmission_states(db_path=path, divergences=())

    assert results == ()
    status = {item.step_key: item for item in AnalysisStatusStore(path).load()}
    assert status["transmission_state"].status == "COMPLETE"
    assert "Ingen nye modne" in status["transmission_state"].detail


def test_transmission_runtime_persists_resolved_state_and_status(tmp_path):
    path = tmp_path / "transmission-runtime.db"

    results = runtime.produce_transmission_states(db_path=path, divergences=(_divergence(),))

    assert len(results) == 1
    assert results[0].dominant_channel == "RATES_FX"
    assert results[0].support_levels["RATES_FX"] == "SUPPORTED"
    persisted = TransmissionStateStore(path).load_latest(market="Silver")
    assert persisted is not None
    assert persisted.transmission_id == results[0].transmission_id
    status = {item.step_key: item for item in AnalysisStatusStore(path).load()}
    assert status["transmission_state"].status == "COMPLETE"
    assert "1 resolved" in status["transmission_state"].detail
    assert "RATES_FX=1" in status["transmission_state"].detail


def test_transmission_runtime_failure_is_degraded(tmp_path, monkeypatch):
    path = tmp_path / "transmission-runtime.db"

    def fail_build(item):
        raise RuntimeError("synthetic transmission failure")

    monkeypatch.setattr(runtime, "build_transmission_state", fail_build)

    results = runtime.produce_transmission_states(db_path=path, divergences=(_divergence(),))

    assert results == ()
    status = {item.step_key: item for item in AnalysisStatusStore(path).load()}
    assert status["transmission_state"].status == "FAILED"
    assert "synthetic transmission failure" in status["transmission_state"].detail


def test_response_divergence_runtime_hooks_transmission_on_healthy_noop(tmp_path, monkeypatch):
    path = tmp_path / "response-hook.db"
    calls: list[tuple] = []

    monkeypatch.setattr(response_divergence_runtime, "refresh_response_divergences", lambda *args, **kwargs: ())

    def record_transmission(*, db_path, divergences, status_store):
        calls.append(divergences)
        status_store.complete("transmission_state", "hook called")
        return ()

    monkeypatch.setattr(response_divergence_runtime, "produce_transmission_states", record_transmission)

    results = response_divergence_runtime.produce_response_divergences(db_path=path)

    assert results == ()
    assert calls == [()]
    status = {item.step_key: item for item in AnalysisStatusStore(path).load()}
    assert status["transmission_state"].status == "COMPLETE"
    assert status["transmission_state"].detail == "hook called"


def test_response_divergence_failure_skips_transmission(tmp_path, monkeypatch):
    path = tmp_path / "response-failure.db"

    def fail_refresh(*args, **kwargs):
        raise RuntimeError("synthetic divergence failure")

    monkeypatch.setattr(response_divergence_runtime, "refresh_response_divergences", fail_refresh)

    response_divergence_runtime.produce_response_divergences(db_path=path)

    status = {item.step_key: item for item in AnalysisStatusStore(path).load()}
    assert status["response_divergence"].status == "FAILED"
    assert status["transmission_state"].status == "SKIPPED"
