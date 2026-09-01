from __future__ import annotations

from dataclasses import dataclass

from autotrader_macd_dry_run_v2 import STRATEGY_KEY as MACD_LONG_FLAT_STRATEGY_V2
from autotrader_macd_flip_policy_v2 import MACD_FLIP_STRATEGY_V2


MACD_SHORT_FLAT_STRATEGY_V2 = "macd-30m-short-flat-v1"
FAST_15M_LONG_FLAT_SHADOW_STRATEGY_V2 = "macd-15m-long-flat-shadow-v1"
MTF_LONG_ENTRY_SHADOW_STRATEGY_V2 = "macd-mtf-long-entry-shadow-v1"
INTRABAR_30M_LONG_FLAT_STRATEGY_V2 = "macd-30m-intrabar-1m-long-flat-v1"
INTRABAR_30M_LONG_FLAT_SHADOW_STRATEGY_V2 = "macd-30m-intrabar-1m-long-flat-shadow-v1"


@dataclass(frozen=True, slots=True)
class AutoTraderStrategySpecV2:
    key: str
    label: str
    description: str
    can_long: bool
    can_short: bool


@dataclass(frozen=True, slots=True)
class AutoManagerStrategyTemplateV2:
    """Named strategy recipe used during AutoManager experimentation.

    Templates describe signal recipes. LIVE authority is still granted only through
    ``AUTOTRADER_STRATEGIES_V2`` plus an explicit LIVE strategy enrollment; a template
    entry by itself never grants order authority.
    """

    key: str
    label: str
    description: str
    signal_stack: str
    live_ready: bool
    shadow_running: bool


MACD_FLIP_SPEC_V2 = AutoTraderStrategySpecV2(
    key=MACD_FLIP_STRATEGY_V2,
    label="30m MACD flip · long/short",
    description="LONG on bullish cross; SHORT on bearish cross.",
    can_long=True,
    can_short=True,
)

MACD_LONG_FLAT_SPEC_V2 = AutoTraderStrategySpecV2(
    key=MACD_LONG_FLAT_STRATEGY_V2,
    label="30m MACD long/flat · defensive",
    description="LONG on bullish closed-30m cross; FLAT/cash on bearish closed-30m cross.",
    can_long=True,
    can_short=False,
)

MACD_SHORT_FLAT_SPEC_V2 = AutoTraderStrategySpecV2(
    key=MACD_SHORT_FLAT_STRATEGY_V2,
    label="30m MACD short/flat · defensive",
    description="SHORT on bearish cross; FLAT/cash on bullish cross.",
    can_long=False,
    can_short=True,
)

MACD_INTRABAR_LONG_FLAT_SPEC_V2 = AutoTraderStrategySpecV2(
    key=INTRABAR_30M_LONG_FLAT_STRATEGY_V2,
    label="Intrabar 30m · 1m cross",
    description=(
        "30m MACD 12/26/9 sampled on every fully observed canonical 1m close; "
        "LONG on bullish cross and FLAT/cash on bearish cross without waiting for the 30m close."
    ),
    can_long=True,
    can_short=False,
)

# Explicit execution-capable catalog. Enrollment + execution gates remain required;
# appearing here never places or arms an order by itself.
AUTOTRADER_STRATEGIES_V2 = (
    MACD_LONG_FLAT_SPEC_V2,
    MACD_SHORT_FLAT_SPEC_V2,
    MACD_FLIP_SPEC_V2,
    MACD_INTRABAR_LONG_FLAT_SPEC_V2,
)

AUTOMANAGER_CLASSIC_30M_TEMPLATE_V2 = AutoManagerStrategyTemplateV2(
    key=MACD_LONG_FLAT_STRATEGY_V2,
    label="Classic 30m",
    description="Closed 30m MACD 12/26/9 controls LONG/FLAT directly.",
    signal_stack="30m regime + 30m entry/exit",
    live_ready=True,
    shadow_running=True,
)

AUTOMANAGER_FAST_15M_TEMPLATE_V2 = AutoManagerStrategyTemplateV2(
    key=FAST_15M_LONG_FLAT_SHADOW_STRATEGY_V2,
    label="Fast 15m",
    description="Closed 15m MACD 12/26/9 controls LONG/FLAT for earlier reactions.",
    signal_stack="15m entry + 15m exit",
    live_ready=False,
    shadow_running=True,
)

AUTOMANAGER_MTF_TEMPLATE_V2 = AutoManagerStrategyTemplateV2(
    key=MTF_LONG_ENTRY_SHADOW_STRATEGY_V2,
    label="MTF 30/10/5",
    description="30m context, 5m entry trigger, 10m validation and 30m regime confirmation.",
    signal_stack="30m regime -> 5m entry -> 10m validation -> 30m confirmation",
    live_ready=False,
    shadow_running=True,
)

AUTOMANAGER_INTRABAR_30M_TEMPLATE_V2 = AutoManagerStrategyTemplateV2(
    key=INTRABAR_30M_LONG_FLAT_STRATEGY_V2,
    label="Intrabar 30m · 1m cross",
    description=(
        "30m MACD 12/26/9 is re-evaluated on every closed canonical 1m sample; "
        "the first observed intrabar cross is actionable instead of waiting for the 30m close."
    ),
    signal_stack="forming 30m MACD sampled on canonical 1m closes -> immediate LONG/FLAT transition",
    live_ready=True,
    # The historical shadow daemon remains a separate capability; LIVE uses the same pure sample function.
    shadow_running=False,
)

AUTOMANAGER_STRATEGY_TEMPLATES_V2 = (
    AUTOMANAGER_CLASSIC_30M_TEMPLATE_V2,
    AUTOMANAGER_FAST_15M_TEMPLATE_V2,
    AUTOMANAGER_MTF_TEMPLATE_V2,
    AUTOMANAGER_INTRABAR_30M_TEMPLATE_V2,
)

_BY_KEY = {item.key: item for item in AUTOTRADER_STRATEGIES_V2}


def strategy_spec_v2(strategy_key: str) -> AutoTraderStrategySpecV2:
    try:
        return _BY_KEY[str(strategy_key)]
    except KeyError as exc:
        raise ValueError(f"unsupported AutoTrader strategy: {strategy_key}") from exc


__all__ = [
    "AUTOMANAGER_CLASSIC_30M_TEMPLATE_V2",
    "AUTOMANAGER_FAST_15M_TEMPLATE_V2",
    "AUTOMANAGER_INTRABAR_30M_TEMPLATE_V2",
    "AUTOMANAGER_MTF_TEMPLATE_V2",
    "AUTOMANAGER_STRATEGY_TEMPLATES_V2",
    "AUTOTRADER_STRATEGIES_V2",
    "AutoManagerStrategyTemplateV2",
    "AutoTraderStrategySpecV2",
    "FAST_15M_LONG_FLAT_SHADOW_STRATEGY_V2",
    "INTRABAR_30M_LONG_FLAT_SHADOW_STRATEGY_V2",
    "INTRABAR_30M_LONG_FLAT_STRATEGY_V2",
    "MACD_FLIP_SPEC_V2",
    "MACD_INTRABAR_LONG_FLAT_SPEC_V2",
    "MACD_LONG_FLAT_SPEC_V2",
    "MACD_LONG_FLAT_STRATEGY_V2",
    "MACD_SHORT_FLAT_SPEC_V2",
    "MACD_SHORT_FLAT_STRATEGY_V2",
    "MTF_LONG_ENTRY_SHADOW_STRATEGY_V2",
    "strategy_spec_v2",
]
