"""V3 phase timings have no trading authority and never expose identities."""
from __future__ import annotations
from pathlib import Path

import v3_runtime_timing_v1 as timing


def test_timing_reports_once_per_window_with_bounded_aggregates(monkeypatch, caplog):
    monkeypatch.setattr(timing, "_STARTED", 100.0)
    timing._SAMPLES.clear()
    with caplog.at_level("INFO"):
        timing.record_v3_phase_v1("inventory", 0.2, now=101.0)
        timing.record_v3_phase_v1("inventory", 0.6, now=161.0)
    assert caplog.text.count("v3 LIVE PHASE 60s") == 1
    assert "inventory:n=2,avg_ms=400" in caplog.text
    assert "max_ms=600" in caplog.text
    assert not timing._SAMPLES


def test_invalid_phase_and_duration_are_ignored():
    timing.record_v3_phase_v1("account_secret", 2.0)
    timing.record_v3_phase_v1("accounts", float("nan"))
    timing.record_v3_phase_v1("accounts", -1.0)
    assert "account_secret" not in timing._SAMPLES


def test_profiling_preserves_exact_v3_broker_guards():
    source = Path("autotrader_v3_live_runtime_v1.py").read_text()
    assert "record_v3_phase_v1('inventory'" in source
    assert "record_v3_phase_v1('decision'" in source
    assert "record_v3_phase_v1('precheck'" in source
    assert "record_v3_phase_v1('submit'" in source
    assert source.index("pre=broker.precheck(order)") < source.index("reserve_order_v3(request_key")
    assert source.index("claim_reserved_for_submission_v3(request_key") < source.index("broker.place_order(order,confirm_live=True)")
