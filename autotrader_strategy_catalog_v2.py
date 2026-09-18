from __future__ import annotations

from dataclasses import dataclass

from autotrader_macd_dry_run_v2 import STRATEGY_KEY as MACD_LONG_FLAT_STRATEGY_V2
from autotrader_macd_flip_policy_v2 import MACD_FLIP_STRATEGY_V2
from autotrader_overseer_performance_v1 import OVERSEER_PERFORMANCE_STRATEGY_KEY_V1

MACD_SHORT_FLAT_STRATEGY_V2 = "macd-30m-short-flat-v1"
MTF_LONG_FLAT_STRATEGY_V2 = "macd-mtf-30-10-5-long-flat-v1"
MTF_SHORT_FLAT_STRATEGY_V2 = "macd-mtf-30-10-5-short-flat-v1"
MTF_LONG_SHORT_FLIP_STRATEGY_V2 = "macd-mtf-30-10-5-long-short-v1"
FAST_15M_LONG_FLAT_SHADOW_STRATEGY_V2 = "macd-15m-long-flat-shadow-v1"
MTF_LONG_ENTRY_SHADOW_STRATEGY_V2 = "macd-mtf-long-entry-shadow-v1"
INTRABAR_30M_LONG_FLAT_SHADOW_STRATEGY_V2 = "macd-30m-intrabar-1m-long-flat-shadow-v1"
COCKTAIL_MODE_1_SHADOW_STRATEGY_V2 = "cocktail-mode-1-shadow-v1"
STRONG_COCKTAIL_STRATEGY_V2 = "strong-cocktail-shadow-v1"
MACD_1M_FLIP_STRATEGY_V2 = "macd-1m-flip-control-shadow-v1"
MACD_2M_FLIP_STRATEGY_V2 = "macd-2m-flip-control-shadow-v1"
MACD_5M_FLIP_STRATEGY_V2 = "macd-5m-flip-control-shadow-v1"
MACD_15M_FLIP_STRATEGY_V2 = "macd-15m-flip-control-shadow-v1"
MACD2_10_STRATEGY_V1 = "macd2-10-v1"
MACD2_S_STRATEGY_V1 = "macd2-s-v1"
MACD_A_STRATEGY_V1 = "macd-a-v1"
MACD_NORM_STRATEGY_V1 = "macd-norm-v1"
MACD_NORM_MANAGER_STRATEGY_V1 = "macd-norm-manager-v1"
SFL_1M_STRATEGY_V1 = "sfl-1m-v1"
SFL_2M_STRATEGY_V1 = "sfl-2m-v1"
SFL_5M_STRATEGY_V1 = "sfl-5m-v1"
SFL_10M_STRATEGY_V1 = "sfl-10m-v1"
MACD_HYBRID_EXIT_1M_ENTRY_2M_STRATEGY_V2 = "macd-hybrid-exit-1m-entry-2m-v1"
MACD_HYBRID_EXIT_1M_ENTRY_5M_STRATEGY_V2 = "macd-hybrid-exit-1m-entry-5m-v1"
AI_BASELINE_STRATEGY_V2 = "gpt-5-mini-ai-baseline-v1"

@dataclass(frozen=True, slots=True)
class AutoTraderStrategySpecV2:
    key: str
    label: str
    description: str
    can_long: bool
    can_short: bool

@dataclass(frozen=True, slots=True)
class AutoManagerStrategyTemplateV2:
    key: str
    label: str
    description: str
    signal_stack: str
    live_ready: bool
    shadow_running: bool

def _spec(key: str, label: str, description: str, long: bool = True, short: bool = True) -> AutoTraderStrategySpecV2:
    return AutoTraderStrategySpecV2(key, label, description, long, short)

MACD_FLIP_SPEC_V2 = _spec(MACD_FLIP_STRATEGY_V2, "MACD30", "30m MACD 12/26/9: LONG on bullish cross; SHORT on bearish cross.")
MACD_LONG_FLAT_SPEC_V2 = _spec(MACD_LONG_FLAT_STRATEGY_V2, "30m MACD long/flat · defensive", "LONG on bullish cross; FLAT/cash on bearish cross.", True, False)
MACD_SHORT_FLAT_SPEC_V2 = _spec(MACD_SHORT_FLAT_STRATEGY_V2, "30m MACD short/flat · defensive", "SHORT on bearish cross; FLAT/cash on bullish cross.", False, True)
MTF_LONG_FLAT_SPEC_V2 = _spec(MTF_LONG_FLAT_STRATEGY_V2, "MTF 30/10/5 · long/flat", "30m context; 5m entry; 10m validation; 30m confirmation.", True, False)
MTF_SHORT_FLAT_SPEC_V2 = _spec(MTF_SHORT_FLAT_STRATEGY_V2, "MTF 30/10/5 · short/flat", "30m bearish context; 5m entry; 10m validation; 30m confirmation.", False, True)
# Keep the direction capabilities explicit: wiring tests and entry gates treat these as a safety contract.
MTF_LONG_SHORT_FLIP_SPEC_V2 = AutoTraderStrategySpecV2(
    key=MTF_LONG_SHORT_FLIP_STRATEGY_V2,
    label="MTF 30/10/5 · long/short flip",
    description="Symmetric MTF with safe CLOSE -> FLAT -> OPEN reversals.",
    can_long=True,
    can_short=True,
)
STRONG_COCKTAIL_SPEC_V2 = _spec(STRONG_COCKTAIL_STRATEGY_V2, "Strong Cocktail · 1m event + MTF context", "Fast 1m event timing with 5/10/15/30m context.")
MACD_1M_FLIP_SPEC_V2 = _spec(MACD_1M_FLIP_STRATEGY_V2, "MACD1", "1m MACD 12/26/9 binary LONG/SHORT control.")
MACD_2M_FLIP_SPEC_V2 = _spec(MACD_2M_FLIP_STRATEGY_V2, "MACD2", "2m MACD 12/26/9 binary LONG/SHORT control.")
MACD_5M_FLIP_SPEC_V2 = _spec(MACD_5M_FLIP_STRATEGY_V2, "MACD5", "5m MACD 12/26/9 binary LONG/SHORT control.")
MACD_15M_FLIP_SPEC_V2 = _spec(MACD_15M_FLIP_STRATEGY_V2, "MACD15", "15m MACD 12/26/9 binary LONG/SHORT control.")
MACD2_10_SPEC_V2 = _spec(MACD2_10_STRATEGY_V1, "MACD2-10", "2m direction with 10m regime filter.")
MACD2_S_SPEC_V2 = _spec(MACD2_S_STRATEGY_V1, "MACD2-S", "2m MACD with bounded stochastic timing adjustment.")
MACD_A_SPEC_V2 = _spec(MACD_A_STRATEGY_V1, "MACD-A", "Adaptive 1m/2m/5m MACD selected from follow-through versus noise.")
MACD_NORM_SPEC_V1 = _spec(
    MACD_NORM_STRATEGY_V1,
    "MACD norm",
    "1/2/5/10/15/30m MACD normalized per timeframe before supervisor scoring; closed 5m MACD cross is an authoritative LONG/SHORT backstop.",
)
MACD_NORM_MANAGER_SPEC_V1 = _spec(
    MACD_NORM_MANAGER_STRATEGY_V1,
    "MACD norm + manager",
    "Normalized MACD signal with authoritative closed 5m cross, plus stateful MFE profit-lock, reversal confirmation and re-entry cooldown.",
)

def _sfl_spec(minutes: int) -> AutoTraderStrategySpecV2:
    return _spec(f"sfl-{minutes}m-v1", f"SFL{minutes}", f"{minutes}m state/flow/latency model with FLAT de-risking.")

SFL_1M_SPEC_V2 = _sfl_spec(1)
SFL_2M_SPEC_V2 = _sfl_spec(2)
SFL_5M_SPEC_V2 = _sfl_spec(5)
SFL_10M_SPEC_V2 = _sfl_spec(10)
MACD_HYBRID_EXIT_1M_ENTRY_2M_SPEC_V2 = _spec(MACD_HYBRID_EXIT_1M_ENTRY_2M_STRATEGY_V2, "MACD hybrid · exit 1m / entry 2m", "1m defensive exit; 2m confirmed entry; safe reversal lifecycle.")
MACD_HYBRID_EXIT_1M_ENTRY_5M_SPEC_V2 = _spec(MACD_HYBRID_EXIT_1M_ENTRY_5M_STRATEGY_V2, "MACD hybrid · exit 1m / entry 5m", "1m defensive exit; 5m confirmed entry; safe reversal lifecycle.")
AI_BASELINE_SPEC_V2 = _spec(AI_BASELINE_STRATEGY_V2, "AI baseline · GPT-5 mini · technicals + news", "Experimental AI policy; normal execution lifecycle remains authoritative.")
OVERSEER_PERFORMANCE_SPEC_V1 = _spec(OVERSEER_PERFORMANCE_STRATEGY_KEY_V1, "Overseer", "Meta-policy selects the currently strongest live-capable expert from recent simulator performance; FLAT and hysteresis are first-class.")

AUTOTRADER_STRATEGIES_V2 = (
    MACD_LONG_FLAT_SPEC_V2, MACD_SHORT_FLAT_SPEC_V2, MACD_FLIP_SPEC_V2,
    MTF_LONG_FLAT_SPEC_V2, MTF_SHORT_FLAT_SPEC_V2, MTF_LONG_SHORT_FLIP_SPEC_V2,
    STRONG_COCKTAIL_SPEC_V2, MACD_1M_FLIP_SPEC_V2, MACD_2M_FLIP_SPEC_V2,
    MACD_5M_FLIP_SPEC_V2, MACD_15M_FLIP_SPEC_V2, MACD2_10_SPEC_V2,
    MACD2_S_SPEC_V2, MACD_A_SPEC_V2, MACD_NORM_SPEC_V1, MACD_NORM_MANAGER_SPEC_V1,
    SFL_1M_SPEC_V2, SFL_2M_SPEC_V2, SFL_5M_SPEC_V2, SFL_10M_SPEC_V2,
    MACD_HYBRID_EXIT_1M_ENTRY_2M_SPEC_V2, MACD_HYBRID_EXIT_1M_ENTRY_5M_SPEC_V2,
    AI_BASELINE_SPEC_V2, OVERSEER_PERFORMANCE_SPEC_V1,
)
PAPER_30M_STRATEGIES_V2 = (MACD_LONG_FLAT_SPEC_V2, MACD_SHORT_FLAT_SPEC_V2, MACD_FLIP_SPEC_V2)

AUTOMANAGER_CLASSIC_30M_TEMPLATE_V2 = AutoManagerStrategyTemplateV2(MACD_LONG_FLAT_STRATEGY_V2, "Classic 30m", "Closed 30m MACD controls LONG/FLAT.", "30m regime + 30m entry/exit", True, True)
AUTOMANAGER_FAST_15M_TEMPLATE_V2 = AutoManagerStrategyTemplateV2(FAST_15M_LONG_FLAT_SHADOW_STRATEGY_V2, "Fast 15m", "Closed 15m MACD controls LONG/FLAT.", "15m entry + 15m exit", False, True)
AUTOMANAGER_MTF_TEMPLATE_V2 = AutoManagerStrategyTemplateV2(MTF_LONG_FLAT_STRATEGY_V2, "MTF 30/10/5 · long", "30m context, 5m entry, 10m validation.", "30m -> 5m -> 10m", True, True)
AUTOMANAGER_MTF_SHORT_TEMPLATE_V2 = AutoManagerStrategyTemplateV2(MTF_SHORT_FLAT_STRATEGY_V2, "MTF 30/10/5 · short", "30m bearish context, 5m entry, 10m validation.", "30m -> 5m -> 10m", True, False)
AUTOMANAGER_MTF_FLIP_TEMPLATE_V2 = AutoManagerStrategyTemplateV2(MTF_LONG_SHORT_FLIP_STRATEGY_V2, "MTF 30/10/5 · long/short flip", "Symmetric MTF with safe reversals.", "30m -> 5m -> 10m -> CLOSE/FLAT/OPEN", True, False)
AUTOMANAGER_INTRABAR_30M_TEMPLATE_V2 = AutoManagerStrategyTemplateV2(INTRABAR_30M_LONG_FLAT_SHADOW_STRATEGY_V2, "Intrabar 30m · 1m cross", "30m MACD sampled on canonical 1m closes.", "forming 30m on 1m clock", False, False)
AUTOMANAGER_COCKTAIL_MODE_1_TEMPLATE_V2 = AutoManagerStrategyTemplateV2(COCKTAIL_MODE_1_SHADOW_STRATEGY_V2, "Cocktail Mode #1", "Adaptive 1m-clock MTF engine.", "1m clock -> 5/10/15/30m context", False, True)
AUTOMANAGER_STRATEGY_TEMPLATES_V2 = (AUTOMANAGER_CLASSIC_30M_TEMPLATE_V2, AUTOMANAGER_FAST_15M_TEMPLATE_V2, AUTOMANAGER_MTF_TEMPLATE_V2, AUTOMANAGER_MTF_SHORT_TEMPLATE_V2, AUTOMANAGER_MTF_FLIP_TEMPLATE_V2, AUTOMANAGER_INTRABAR_30M_TEMPLATE_V2, AUTOMANAGER_COCKTAIL_MODE_1_TEMPLATE_V2)

_BY_KEY = {item.key: item for item in AUTOTRADER_STRATEGIES_V2}
_TEMPLATE_BY_KEY = {item.key: item for item in AUTOMANAGER_STRATEGY_TEMPLATES_V2}

def strategy_spec_v2(strategy_key: str) -> AutoTraderStrategySpecV2:
    try:
        return _BY_KEY[str(strategy_key)]
    except KeyError as exc:
        raise ValueError(f"unsupported AutoTrader strategy: {strategy_key}") from exc

def strategy_display_label_v2(strategy_key: str) -> str:
    key = str(strategy_key)
    if key in _BY_KEY:
        return _BY_KEY[key].label
    if key in _TEMPLATE_BY_KEY:
        return _TEMPLATE_BY_KEY[key].label
    return key

__all__ = [name for name in globals() if name.isupper()] + [
    "AutoManagerStrategyTemplateV2", "AutoTraderStrategySpecV2", "strategy_display_label_v2", "strategy_spec_v2"
]
