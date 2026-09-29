"""V3 strategy registry: pure closed-bar decisions, independent of Saxo execution.

Adding a strategy requires registering its key and decision adapter here, not
editing the broker/runtime order path. LIVE eligibility is a separate safety gate.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from autotrader_v3_macd_histogram_v1 import STRATEGY_KEY_V3 as HISTOGRAM_KEY
from autotrader_v3_macd_trailing_v1 import STRATEGY_KEY_V3 as TRAILING_KEY
from autotrader_v3_closed_bar_driver_v1 import evaluate_closed_bar_once_v3


@dataclass(frozen=True)
class StrategyAdapterV3:
    key: str
    evaluate_closed_bar: Callable
    live_route_enabled: bool = False  # Existing route availability; not proof of durable reconciliation.


STRATEGIES_V3: dict[str, StrategyAdapterV3] = {
    key: StrategyAdapterV3(key=key, evaluate_closed_bar=evaluate_closed_bar_once_v3,
                           live_route_enabled=True)
    for key in (HISTOGRAM_KEY, TRAILING_KEY)
}


def strategy_adapter_v3(key: str) -> StrategyAdapterV3:
    try:
        return STRATEGIES_V3[key]
    except KeyError as exc:
        raise ValueError(f"Unregistered V3 strategy: {key}") from exc


def evaluate_strategy_bar_v3(*, strategy_key: str, trader_id: str, observation, db_path="pricegauger.db"):
    adapter = strategy_adapter_v3(strategy_key)
    return adapter.evaluate_closed_bar(
        trader_id=trader_id, observation=observation,
        strategy_key=adapter.key, db_path=db_path,
    )
