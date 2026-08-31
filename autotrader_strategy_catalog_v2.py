from __future__ import annotations

from dataclasses import dataclass

from autotrader_macd_dry_run_v2 import STRATEGY_KEY as MACD_LONG_FLAT_STRATEGY_V2
from autotrader_macd_flip_policy_v2 import MACD_FLIP_STRATEGY_V2


MACD_SHORT_FLAT_STRATEGY_V2 = "macd-30m-short-flat-v1"


@dataclass(frozen=True, slots=True)
class AutoTraderStrategySpecV2:
    key: str
    label: str
    description: str
    can_long: bool
    can_short: bool


MACD_FLIP_SPEC_V2 = AutoTraderStrategySpecV2(
    key=MACD_FLIP_STRATEGY_V2,
    label="MACD Switch · long/short",
    description="Bullish cross → LONG; bearish cross → SHORT.",
    can_long=True,
    can_short=True,
)

MACD_LONG_FLAT_SPEC_V2 = AutoTraderStrategySpecV2(
    key=MACD_LONG_FLAT_STRATEGY_V2,
    label="Long / Flat",
    description="Bullish cross → LONG; bearish cross → FLAT/cash.",
    can_long=True,
    can_short=False,
)

MACD_SHORT_FLAT_SPEC_V2 = AutoTraderStrategySpecV2(
    key=MACD_SHORT_FLAT_STRATEGY_V2,
    label="Short / Flat",
    description="Bearish cross → SHORT; bullish cross → FLAT/cash.",
    can_long=False,
    can_short=True,
)

AUTOTRADER_STRATEGIES_V2 = (
    MACD_LONG_FLAT_SPEC_V2,
    MACD_SHORT_FLAT_SPEC_V2,
    MACD_FLIP_SPEC_V2,
)

_BY_KEY = {item.key: item for item in AUTOTRADER_STRATEGIES_V2}


def strategy_spec_v2(strategy_key: str) -> AutoTraderStrategySpecV2:
    try:
        return _BY_KEY[str(strategy_key)]
    except KeyError as exc:
        raise ValueError(f"unsupported AutoTrader strategy: {strategy_key}") from exc


__all__ = [
    "AUTOTRADER_STRATEGIES_V2",
    "AutoTraderStrategySpecV2",
    "MACD_FLIP_SPEC_V2",
    "MACD_LONG_FLAT_SPEC_V2",
    "MACD_LONG_FLAT_STRATEGY_V2",
    "MACD_SHORT_FLAT_SPEC_V2",
    "MACD_SHORT_FLAT_STRATEGY_V2",
    "strategy_spec_v2",
]
