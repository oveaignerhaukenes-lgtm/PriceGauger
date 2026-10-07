from pathlib import Path


def test_v3_live_has_dedicated_fast_loop_in_continuous_worker():
    source = Path("worker.py").read_text(encoding="utf-8")
    assert "V3_LIVE_INTERVAL_SECONDS = 30" in source
    assert "def _run_v3_live_forever(" in source
    assert 'name="pricegauger-v3-live"' in source
    assert "include_v3_live=False" in source
    assert "stop_event.wait(remaining)" in source


def test_slow_worker_cycle_cannot_be_live_execution_cadence():
    source = Path("worker.py").read_text(encoding="utf-8")
    # Production continuous mode delegates V3 LIVE to the dedicated fast loop.
    forever = source[source.index("def run_forever("):]
    assert "include_v3_live=False" in forever
    assert "v3_thread.start()" in forever


def test_live_runtime_uses_configured_timeframe_and_latest_closed_bar():
    source = Path("autotrader_v3_live_runtime_v1.py").read_text(encoding="utf-8")
    assert "timeframe_minutes=_live_timeframe_minutes_v3(config.timeframe)" in source
    assert "macd_observations_v2(closed,timeframe_minutes=timeframe_minutes)" in source
    assert "observation=obs[-1]" in source
