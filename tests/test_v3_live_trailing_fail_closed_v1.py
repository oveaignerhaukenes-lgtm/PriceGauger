from pathlib import Path

from autotrader_v3_strategy_registry_v1 import strategy_capability_v3
from autotrader_v3_macd_trailing_v1 import STRATEGY_KEY_V3 as TRAILING_KEY
from autotrader_v3_macd_histogram_v1 import STRATEGY_KEY_V3 as HISTOGRAM_KEY

RUNTIME = Path("autotrader_v3_live_runtime_v1.py").read_text(encoding="utf-8")
DESK = Path("tradingdesk_automanager_simple_v1.py").read_text(encoding="utf-8")
DRIVER = Path("autotrader_v3_closed_bar_driver_v1.py").read_text(encoding="utf-8")


def test_tradingdesk_trailing_strategy_cannot_silently_run_histogram_live():
    assert "from autotrader_v3_macd_trailing_v1 import STRATEGY_KEY_V3" in DESK
    assert "decide = macd_trailing_target_v3 if strategy_key == TRAILING_KEY else macd_histogram_target_v3" in DRIVER
    assert strategy_capability_v3(TRAILING_KEY).closed_bar_driver
    assert not strategy_capability_v3(TRAILING_KEY).live_execution_validated
    assert strategy_capability_v3(HISTOGRAM_KEY).live_execution_validated
    assert "strategy_capability_v3(e.strategy_key)" in RUNTIME
    assert "elif not capability.live_execution_validated:" in RUNTIME
    assert '_record_runtime(e.pilot_key,"BLOCKED"' in RUNTIME
    assert "No orders sent." in RUNTIME
