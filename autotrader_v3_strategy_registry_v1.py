"""V3 strategy capability registry; never infer LIVE authority from UI selection."""
from __future__ import annotations
from dataclasses import dataclass
from autotrader_v3_macd_histogram_v1 import STRATEGY_KEY_V3 as HISTOGRAM
from autotrader_v3_macd_trailing_v1 import STRATEGY_KEY_V3 as TRAILING

@dataclass(frozen=True)
class StrategyCapabilityV3:
    key: str
    timeframe_minutes: int
    closed_bar_driver: bool
    live_execution_validated: bool

# Strategies register decision capabilities separately from broker authority.
STRATEGIES_V3 = {
    HISTOGRAM: StrategyCapabilityV3(HISTOGRAM, 5, True, True),
    TRAILING: StrategyCapabilityV3(TRAILING, 5, True, False),
}

def strategy_capability_v3(key: str) -> StrategyCapabilityV3 | None:
    return STRATEGIES_V3.get(key)
