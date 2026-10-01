from pathlib import Path
from autotrader_v3_macd_trailing_v1 import STRATEGY_KEY_V3 as TRAILING_KEY
from autotrader_v3_strategy_registry_v1 import STRATEGIES_V3

RUNTIME = Path("autotrader_v3_live_runtime_v1.py").read_text(encoding="utf-8")
DESK = Path("tradingdesk_automanager_simple_v1.py").read_text(encoding="utf-8")
DRIVER = Path("autotrader_v3_closed_bar_driver_v1.py").read_text(encoding="utf-8")


def test_tradingdesk_trailing_strategy_cannot_silently_run_histogram_live():
    assert "from autotrader_v3_macd_trailing_v1 import STRATEGY_KEY_V3" in DESK
    assert "strategy_key == STOCH_KEY" in DRIVER
    assert "macd_stoch_target_v3" in DRIVER
    assert "macd_trailing_target_v3" in DRIVER
    assert "macd_histogram_target_v3" in DRIVER
    assert STRATEGIES_V3[TRAILING_KEY].live_route_enabled is True
    assert "mutation.action in {'OPEN','ADD'}" in RUNTIME
    assert 'load_execution_policy_v3' in RUNTIME
    assert 'cap_open_add_amount_v3' in RUNTIME
    assert 'mutation.amount > abs(actual.amount) + 1e-9' in RUNTIME
    assert "STRATEGIES_V3.get(e.strategy_key)" in RUNTIME
    assert "not adapter.live_route_enabled" in RUNTIME
    assert '"BLOCKED"' in RUNTIME
    assert "No orders sent." in RUNTIME
    assert "evaluate_strategy_bar_v3(" in RUNTIME
