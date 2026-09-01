from __future__ import annotations

from dataclasses import dataclass

from autotrader_macd_dry_run_v2 import STRATEGY_KEY as MACD_LONG_FLAT_STRATEGY_V2
from autotrader_macd_flip_policy_v2 import MACD_FLIP_STRATEGY_V2


MACD_SHORT_FLAT_STRATEGY_V2 = "macd-30m-short-flat-v1"
MTF_LONG_FLAT_STRATEGY_V2 = "macd-mtf-30-10-5-long-flat-v1"
MTF_SHORT_FLAT_STRATEGY_V2 = "macd-mtf-30-10-5-short-flat-v1"
MTF_LONG_SHORT_FLIP_STRATEGY_V2 = "macd-mtf-30-10-5-long-short-v1"
FAST_15M_LONG_FLAT_SHADOW_STRATEGY_V2 = "macd-15m-long-flat-shadow-v1"
MTF_LONG_ENTRY_SHADOW_STRATEGY_V2 = "macd-mtf-long-entry-shadow-v1"
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

    Templates describe user-facing recipes; execution authority remains explicit in
    ``AUTOTRADER_STRATEGIES_V2``. A template may therefore have a parallel shadow
    runtime without sharing the same persistent strategy key.
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
    description="LONG on bullish cross; FLAT/cash on bearish cross.",
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

MTF_LONG_FLAT_SPEC_V2 = AutoTraderStrategySpecV2(
    key=MTF_LONG_FLAT_STRATEGY_V2,
    label="MTF 30/10/5 · long/flat",
    description=(
        "30m context/regime; closed 5m bullish MACD trigger opens LONG; closed 10m validates or "
        "rejects the provisional entry; closed 30m confirms the regime or ends it on bearish cross."
    ),
    can_long=True,
    can_short=False,
)

MTF_SHORT_FLAT_SPEC_V2 = AutoTraderStrategySpecV2(
    key=MTF_SHORT_FLAT_STRATEGY_V2,
    label="MTF 30/10/5 · short/flat",
    description=(
        "30m bearish/deteriorating context; closed 5m bearish MACD trigger opens SHORT; closed 10m validates or "
        "rejects the provisional entry; closed 30m confirms the regime or ends it on bullish cross."
    ),
    can_long=False,
    can_short=True,
)

MTF_LONG_SHORT_FLIP_SPEC_V2 = AutoTraderStrategySpecV2(
    key=MTF_LONG_SHORT_FLIP_STRATEGY_V2,
    label="MTF 30/10/5 · long/short flip",
    description=(
        "Symmetric MTF: 30m context, closed 5m early LONG/SHORT trigger and closed 10m validation. "
        "An opposite closed 30m cross carries a reversal only through CLOSE -> confirmed FLAT -> OPEN."
    ),
    can_long=True,
    can_short=True,
)

# Explicit execution-capable catalog. Experimental shadow keys below never gain LIVE
# authority merely by existing in the template catalog.
AUTOTRADER_STRATEGIES_V2 = (
    MACD_LONG_FLAT_SPEC_V2,
    MACD_SHORT_FLAT_SPEC_V2,
    MACD_FLIP_SPEC_V2,
    MTF_LONG_FLAT_SPEC_V2,
    MTF_SHORT_FLAT_SPEC_V2,
    MTF_LONG_SHORT_FLIP_SPEC_V2,
)

# These three policies have the established deterministic closed-30m paper replay.
# MTF and intrabar require their own replay clocks and must not be mislabeled as
# closed-30m curves merely because they can run LIVE.
PAPER_30M_STRATEGIES_V2 = (
    MACD_LONG_FLAT_SPEC_V2,
    MACD_SHORT_FLAT_SPEC_V2,
    MACD_FLIP_SPEC_V2,
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
    key=MTF_LONG_FLAT_STRATEGY_V2,
    label="MTF 30/10/5 · long",
    description="30m context, 5m LONG entry trigger, 10m validation and 30m regime confirmation.",
    signal_stack="30m regime -> 5m LONG entry -> 10m validation -> 30m confirmation",
    live_ready=True,
    shadow_running=True,
)

AUTOMANAGER_MTF_SHORT_TEMPLATE_V2 = AutoManagerStrategyTemplateV2(
    key=MTF_SHORT_FLAT_STRATEGY_V2,
    label="MTF 30/10/5 · short",
    description="30m bearish context, 5m SHORT entry trigger, 10m validation and 30m regime confirmation.",
    signal_stack="30m regime -> 5m SHORT entry -> 10m validation -> 30m confirmation",
    live_ready=True,
    shadow_running=False,
)

AUTOMANAGER_MTF_FLIP_TEMPLATE_V2 = AutoManagerStrategyTemplateV2(
    key=MTF_LONG_SHORT_FLIP_STRATEGY_V2,
    label="MTF 30/10/5 · long/short flip",
    description=(
        "30m regime with symmetric 5m early LONG/SHORT entries, 10m validation and safe two-step reversals."
    ),
    signal_stack="30m regime -> 5m LONG/SHORT entry -> 10m validation -> 30m CLOSE/FLAT/opposite OPEN",
    live_ready=True,
    shadow_running=False,
)

AUTOMANAGER_INTRABAR_30M_TEMPLATE_V2 = AutoManagerStrategyTemplateV2(
    key=INTRABAR_30M_LONG_FLAT_SHADOW_STRATEGY_V2,
    label="Intrabar 30m · 1m cross",
    description=(
        "30m MACD 12/26/9 is re-evaluated on every closed canonical 1m sample; "
        "the first observed intrabar cross is timestamped instead of waiting for the 30m close."
    ),
    signal_stack="forming 30m MACD sampled on canonical 1m closes -> immediate LONG/FLAT shadow transition",
    live_ready=False,
    shadow_running=False,
)

AUTOMANAGER_STRATEGY_TEMPLATES_V2 = (
    AUTOMANAGER_CLASSIC_30M_TEMPLATE_V2,
    AUTOMANAGER_FAST_15M_TEMPLATE_V2,
    AUTOMANAGER_MTF_TEMPLATE_V2,
    AUTOMANAGER_MTF_SHORT_TEMPLATE_V2,
    AUTOMANAGER_MTF_FLIP_TEMPLATE_V2,
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
    "AUTOMANAGER_MTF_FLIP_TEMPLATE_V2",
    "AUTOMANAGER_MTF_SHORT_TEMPLATE_V2",
    "AUTOMANAGER_MTF_TEMPLATE_V2",
    "AUTOMANAGER_STRATEGY_TEMPLATES_V2",
    "AUTOTRADER_STRATEGIES_V2",
    "PAPER_30M_STRATEGIES_V2",
    "AutoManagerStrategyTemplateV2",
    "AutoTraderStrategySpecV2",
    "FAST_15M_LONG_FLAT_SHADOW_STRATEGY_V2",
    "INTRABAR_30M_LONG_FLAT_SHADOW_STRATEGY_V2",
    "MACD_FLIP_SPEC_V2",
    "MACD_LONG_FLAT_SPEC_V2",
    "MACD_LONG_FLAT_STRATEGY_V2",
    "MACD_SHORT_FLAT_SPEC_V2",
    "MACD_SHORT_FLAT_STRATEGY_V2",
    "MTF_LONG_ENTRY_SHADOW_STRATEGY_V2",
    "MTF_LONG_FLAT_SPEC_V2",
    "MTF_LONG_FLAT_STRATEGY_V2",
    "MTF_LONG_SHORT_FLIP_SPEC_V2",
    "MTF_LONG_SHORT_FLIP_STRATEGY_V2",
    "MTF_SHORT_FLAT_SPEC_V2",
    "MTF_SHORT_FLAT_STRATEGY_V2",
    "strategy_spec_v2",
]
