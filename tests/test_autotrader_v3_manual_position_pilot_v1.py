from pathlib import Path
from autotrader_v3_strategy_registry_v1 import STRATEGIES_V3
from autotrader_v3_macd_trailing_v1 import STRATEGY_KEY_V3 as TRAILING_KEY

def test_trailing_route_enabled_only_under_existing_user_authority():
    assert STRATEGIES_V3[TRAILING_KEY].live_route_enabled

def test_trailing_pilot_cannot_open_or_add():
    source = Path("autotrader_v3_live_runtime_v1.py").read_text(encoding="utf-8")
    assert 'if e.strategy_key == TRAILING_KEY:' in source
    assert 'mutation.action not in {"REDUCE", "CLOSE"}' in source
    assert 'mutation.amount > abs(actual.amount) + 1e-9' in source
    assert source.index('if e.strategy_key == TRAILING_KEY:') < source.index('broker.precheck(order)')
    assert source.index('if e.strategy_key == TRAILING_KEY:') < source.index('reserve_order_v3(')
