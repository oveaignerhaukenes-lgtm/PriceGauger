"""V3 strategy registry: pure closed-bar decisions, independent of Saxo execution.

Adding a strategy requires registering its key and decision adapter here, not
editing the broker/runtime order path. LIVE eligibility is a separate safety gate.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from autotrader_v3_macd_histogram_v1 import STRATEGY_KEY_V3 as HISTOGRAM_KEY
from autotrader_v3_macd_histogram_flip_build_v1 import STRATEGY_KEY_V3 as HISTOGRAM_FLIP_BUILD_KEY
from autotrader_v3_macd_histogram_peak_flip_v1 import STRATEGY_KEY_V3 as PEAK_FLIP_KEY
from autotrader_v3_macd_flip_v1 import STRATEGY_KEY_V3 as FLIP_KEY
from autotrader_v3_macd_trailing_v1 import STRATEGY_KEY_V3 as TRAILING_KEY
from autotrader_v3_macd_stoch_v1 import STRATEGY_KEY_V3 as STOCH_KEY
from autotrader_v3_macd_stoch_v2 import STRATEGY_KEY_V3 as STOCH_V2_KEY
from autotrader_v3_macd_stoch_v21 import STRATEGY_KEY_V3 as STOCH_V21_KEY
from autotrader_v3_macd_stoch_rhythm_build_v1 import STRATEGY_KEY_V3 as RHYTHM_BUILD_KEY
from autotrader_v3_rhythm_trend_v1 import STRATEGY_KEY_V3 as RHYTHM_TREND_KEY
from autotrader_v3_fractal_rhythm_variants_v1 import (
    RHYTHM_BUILD_FRACTAL_KEY_V3,RHYTHM_TREND_FRACTAL_KEY_V3,
)
from autotrader_v3_vwap_regime_histogram_v1 import STRATEGY_KEY_V3 as VWAP_REGIME_KEY
from autotrader_v3_macd_regime_histogram_v1 import STRATEGY_KEY_V3 as MACD_REGIME_HIST_KEY
from autotrader_v3_aen2_sticky_regime_v1 import STRATEGY_KEY_V3 as AEN2_STICKY_KEY
from autotrader_v3_aen21_sticky_fast_exit_v1 import STRATEGY_KEY_V3 as AEN21_FAST_EXIT_KEY
from autotrader_v3_closed_bar_driver_v1 import evaluate_closed_bar_once_v3
from autotrader_v3_aen_core_bridge_v1 import AEN_CORE_KEYS_V3, evaluate_aen_core_v3
from autotrader_v3_fraktal1_bridge_v1 import FRAKTAL1_RUNTIME_KEYS_V3, evaluate_fraktal1_v3


@dataclass(frozen=True)
class StrategyAdapterV3:
    key: str
    evaluate_closed_bar: Callable
    live_route_enabled: bool = False  # Existing route availability; not proof of durable reconciliation.


STRATEGIES_V3: dict[str, StrategyAdapterV3] = {
    key: StrategyAdapterV3(key=key, evaluate_closed_bar=evaluate_closed_bar_once_v3,
                           live_route_enabled=True)
    for key in (HISTOGRAM_KEY, HISTOGRAM_FLIP_BUILD_KEY, PEAK_FLIP_KEY, VWAP_REGIME_KEY, MACD_REGIME_HIST_KEY, AEN2_STICKY_KEY, AEN21_FAST_EXIT_KEY, TRAILING_KEY, FLIP_KEY, STOCH_KEY, STOCH_V2_KEY, STOCH_V21_KEY)
}


# Registered LIVE routes do not arm accounts or create execution authority.
for rhythm_key in (RHYTHM_BUILD_KEY, RHYTHM_TREND_KEY):
    STRATEGIES_V3[rhythm_key] = StrategyAdapterV3(
        key=rhythm_key, evaluate_closed_bar=evaluate_closed_bar_once_v3,
        live_route_enabled=True,
    )


# Compare Fraktal-cadence variants in SIM only. The shared LIVE worker
# refuses these keys even if a user previously armed the same account.
for rhythm_key in (RHYTHM_BUILD_FRACTAL_KEY_V3, RHYTHM_TREND_FRACTAL_KEY_V3):
    STRATEGIES_V3[rhythm_key] = StrategyAdapterV3(
        key=rhythm_key,evaluate_closed_bar=evaluate_closed_bar_once_v3,
        live_route_enabled=False,
    )

STRATEGIES_V3.update({
    key: StrategyAdapterV3(key=key,evaluate_closed_bar=evaluate_aen_core_v3,
                           live_route_enabled=True)
    for key in AEN_CORE_KEYS_V3
})


# Research-only. LIVE always denies this key before constructing any order.
STRATEGIES_V3.update({
    key: StrategyAdapterV3(key=key, evaluate_closed_bar=evaluate_fraktal1_v3,
                           live_route_enabled=False)
    for key in FRAKTAL1_RUNTIME_KEYS_V3
})


def strategy_adapter_v3(key: str) -> StrategyAdapterV3:
    try:
        return STRATEGIES_V3[key]
    except KeyError as exc:
        raise ValueError(f"Unregistered V3 strategy: {key}") from exc


def evaluate_strategy_bar_v3(*, strategy_key: str, trader_id: str, observation, bars=(),
                             source_bars=(), regime_timeframe_minutes=15, market_name="",
                             config=None, db_path="pricegauger.db",
                             actual_inventory=None,signal_timeframe_minutes=None,now=None):
    adapter = strategy_adapter_v3(strategy_key)
    return adapter.evaluate_closed_bar(
        trader_id=trader_id, observation=observation,
        strategy_key=adapter.key, bars=bars, source_bars=source_bars,
        regime_timeframe_minutes=regime_timeframe_minutes, market_name=market_name,
        config=config, db_path=db_path,
        **({"actual_inventory":actual_inventory,
            "signal_timeframe_minutes":signal_timeframe_minutes,
            "now":now} if strategy_key in (AEN_CORE_KEYS_V3 | FRAKTAL1_RUNTIME_KEYS_V3) else {}),
    )
