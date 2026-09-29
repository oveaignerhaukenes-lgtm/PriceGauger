from autotrader_v3_strategy_registry_v1 import STRATEGIES_V3, strategy_capability_v3
from autotrader_v3_macd_histogram_v1 import STRATEGY_KEY_V3 as HISTOGRAM
from autotrader_v3_macd_trailing_v1 import STRATEGY_KEY_V3 as TRAILING

def test_v3_strategy_registry_separates_decision_and_live_authority():
    assert set(STRATEGIES_V3) == {HISTOGRAM, TRAILING}
    assert all(cap.closed_bar_driver for cap in STRATEGIES_V3.values())
    assert strategy_capability_v3(HISTOGRAM).live_execution_validated
    assert not strategy_capability_v3(TRAILING).live_execution_validated
    assert strategy_capability_v3("unsupported") is None
