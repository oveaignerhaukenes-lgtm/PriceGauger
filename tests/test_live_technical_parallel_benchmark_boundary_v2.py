from __future__ import annotations

from pathlib import Path


def test_live_runtime_keeps_parallel_benchmark_observational():
    source = Path("live_technical_runtime_v2.py").read_text(encoding="utf-8")
    assert "run_parallel_forecast_runtime_cycle_v2" in source
    assert "Benchmark collection is observational" in source
    assert "except Exception as exc:" in source
    assert "v2 parallel benchmark failed" in source
