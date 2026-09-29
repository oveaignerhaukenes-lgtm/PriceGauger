from pathlib import Path

RUNTIME = Path("autotrader_v3_live_runtime_v1.py").read_text(encoding="utf-8")
DESK = Path("tradingdesk_automanager_simple_v1.py").read_text(encoding="utf-8")
DRIVER = Path("autotrader_v3_closed_bar_driver_v1.py").read_text(encoding="utf-8")


def test_tradingdesk_trailing_strategy_cannot_silently_run_histogram_live():
    assert "from autotrader_v3_macd_trailing_v1 import STRATEGY_KEY_V3" in DESK
    assert "from autotrader_v3_macd_histogram_v1 import STRATEGY_KEY_V3" in RUNTIME
    assert "decide = macd_trailing_target_v3 if strategy_key == TRAILING_KEY else macd_histogram_target_v3" in DRIVER
    assert 'if e.strategy_key == TRAILING_KEY_V3:' in RUNTIME
    assert '_record_runtime(e.pilot_key,"BLOCKED"' in RUNTIME
    assert "No orders sent." in RUNTIME
    assert "enrollments=tuple(e for e in active if e.strategy_key==STRATEGY_KEY_V3)" in RUNTIME
