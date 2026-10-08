from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StrategySpecV3:
    key: str
    label: str
    description: str
    runtime_key: str | None = None
    runtime_ready: bool = False


@dataclass(frozen=True, slots=True)
class ModifierSpecV3:
    key: str
    label: str
    description: str
    configurable: bool = True


STRATEGIES_V3 = (
    StrategySpecV3("macd", "MACD", "MACD-regime: motsatt kryss går direkte FLAT; impuls skalerer kun innen aktiv retning.", "macd-trailing-v1", True),
    StrategySpecV3("macd-stoch-v1", "MACD-Stoch", "MACD bygger eksponering trinnvis; motsatt Stochastic K/D-rollover går FLAT uten å reversere.", "macd-stoch-v1", True),
    StrategySpecV3("price-macd", "Price + MACD", "Prisstruktur kombinert med MACD."),
    StrategySpecV3("price-stoch", "Price + Stoch", "Prisstruktur kombinert med Stochastic."),
    StrategySpecV3("sfl", "SFL", "State/flow/latency-grunnstrategi; periode velges separat."),
    StrategySpecV3("macd-histogram", "MACD Histogram", "Histogramretning styrer target inventory direkte.", "macd-histogram-v1", True),
    StrategySpecV3(
        "macd-histogram-flip-build",
        "Histogram Flip+Build",
        "Histogram-slope flipper target direkte til minste tranche på ny side og bygger videre én tranche per ny lukket bar.",
        "macd-histogram-flip-build-v1",
        True,
    ),
    StrategySpecV3(
        "vwap-regime-histogram",
        "VWAP Regime + Histogram",
        "Eksperimentell VWAP-variant; volumgrunnlaget må vurderes per instrument.",
        "vwap-regime-histogram-v1",
        True,
    ),
    StrategySpecV3(
        "macd-regime-histogram",
        "Histogram MACD-RxSy",
        "R-periodens MACD eier retning; S-periodens histogram skalerer eksponering uten motregime-flips.",
        "macd-regime-histogram-v1",
        True,
    ),
    StrategySpecV3(
        "aen2-sticky-regime",
        "Aen#2 · Sticky Regime Rx/Sy",
        "R eier retning. S bygger med regimet; enkelt motrykk HOLD, vedvarende mottrykk + svekkende R reduserer.",
        "aen2-sticky-regime-v1",
        True,
    ),
)

MODIFIERS_V3 = (
    ModifierSpecV3("normalize", "Normalization", "Normaliserer signalstyrke på tvers av valgte tidsvinduer."),
    ModifierSpecV3("mtf-confirmation", "MTF Confirmation", "Bruker høyere/lavere tidsperioder som kontekst uten å endre grunnstrategiens identitet."),
    ModifierSpecV3("impulse", "Impulse Detector", "Forsterker eller demper target ved endring i momentum."),
    ModifierSpecV3("reversal", "Reversal Detector", "Reduserer eller reverserer target ved bekreftet regimeskifte."),
    ModifierSpecV3("take-profit", "Take Profit", "Beskytter opparbeidet gevinst og kan sende target mot FLAT."),
    ModifierSpecV3("reset-on-loss", "Reset on Loss", "Går umiddelbart FLAT når eksisterende posisjons åpne P/L blir negativ; strategien kan deretter bygge opp på nytt."),
    ModifierSpecV3("whipsaw", "Whipsaw Detector", "Demper handel i hakkete/retningsløse perioder."),
    ModifierSpecV3("regime", "Regime Detector", "Klassifiserer markedsregime for adaptive valg."),
)

TIMEFRAMES_V3 = ("1m", "2m", "5m", "10m", "15m", "30m", "1h", "Adaptiv")
CONTROL_MODES_V3 = ("Manuell", "Sim-Adapt", "Overseer", "God Mode")

# Canonical LIVE capability contract. Items may exist in the V3 product/catalog
# before they have a validated production runtime. LIVE must never silently
# ignore a configured setting.
FIXED_TIMEFRAME_MINUTES_V3 = {
    "1m": 1, "2m": 2, "5m": 5, "10m": 10, "15m": 15, "30m": 30, "1h": 60,
}
LIVE_TIMEFRAMES_V3 = tuple(FIXED_TIMEFRAME_MINUTES_V3)
REGIME_TIMEFRAMES_V3 = LIVE_TIMEFRAMES_V3
REGIME_STRATEGIES_V3 = ("macd-regime-histogram", "aen2-sticky-regime")
LIVE_CONTROL_MODES_V3 = ("Manuell",)
LIVE_MODIFIERS_V3 = ("reset-on-loss",)
SIM_TIMEFRAMES_V3 = tuple(FIXED_TIMEFRAME_MINUTES_V3)
SIM_CONTROL_MODES_V3 = ("Manuell",)
SIM_MODIFIERS_V3: tuple[str, ...] = ()


def fixed_timeframe_minutes_v3(timeframe: str) -> int:
    label = str(timeframe or "").strip()
    try:
        return FIXED_TIMEFRAME_MINUTES_V3[label]
    except KeyError as exc:
        raise ValueError(f"unsupported fixed V3 timeframe: {label or '<empty>'}") from exc


def live_config_issues_v3(
    *,
    strategy_key: str,
    timeframe: str,
    control_mode: str,
    modifiers: tuple[str, ...] | list[str],
    regime_timeframe: str = "15m",
) -> tuple[str, ...]:
    issues: list[str] = []
    try:
        spec = strategy_v3(strategy_key)
    except StopIteration:
        return (f"unknown strategy {strategy_key}",)
    if not spec.runtime_ready or not spec.runtime_key:
        issues.append(f"strategy {strategy_key} is not LIVE runtime-ready")
    if timeframe not in LIVE_TIMEFRAMES_V3:
        issues.append(f"timeframe {timeframe} is not LIVE runtime-ready")
    if strategy_key in REGIME_STRATEGIES_V3 and regime_timeframe not in REGIME_TIMEFRAMES_V3:
        issues.append(f"regime timeframe {regime_timeframe} is not LIVE runtime-ready")
    if control_mode not in LIVE_CONTROL_MODES_V3:
        issues.append(f"control mode {control_mode} is not LIVE runtime-ready")
    unsupported = tuple(item for item in modifiers if item not in LIVE_MODIFIERS_V3)
    if unsupported:
        issues.append("modifiers not LIVE runtime-ready: " + ", ".join(unsupported))
    return tuple(issues)


def sim_config_issues_v3(
    *,
    strategy_key: str,
    timeframe: str,
    control_mode: str,
    modifiers: tuple[str, ...] | list[str],
    regime_timeframe: str = "15m",
) -> tuple[str, ...]:
    issues: list[str] = []
    try:
        spec = strategy_v3(strategy_key)
    except StopIteration:
        return (f"unknown strategy {strategy_key}",)
    if not spec.runtime_ready or not spec.runtime_key:
        issues.append(f"strategy {strategy_key} is not SIM runtime-ready")
    if timeframe not in SIM_TIMEFRAMES_V3:
        issues.append(f"timeframe {timeframe} is not SIM runtime-ready")
    if strategy_key in REGIME_STRATEGIES_V3 and regime_timeframe not in REGIME_TIMEFRAMES_V3:
        issues.append(f"regime timeframe {regime_timeframe} is not SIM runtime-ready")
    if control_mode not in SIM_CONTROL_MODES_V3:
        issues.append(f"control mode {control_mode} is not SIM runtime-ready")
    unsupported = tuple(item for item in modifiers if item not in SIM_MODIFIERS_V3)
    if unsupported:
        issues.append("modifiers not SIM runtime-ready: " + ", ".join(unsupported))
    return tuple(issues)


def strategy_v3(key: str) -> StrategySpecV3:
    return next(item for item in STRATEGIES_V3 if item.key == key)


def strategy_display_label_v3(
    strategy_key: str,
    timeframe: str,
    regime_timeframe: str = "15m",
) -> str:
    """Human-facing label for the *persisted* V3 strategy configuration."""
    spec = strategy_v3(str(strategy_key))
    if spec.key == "macd-regime-histogram":
        return f"Histogram MACD-R{regime_timeframe}S{timeframe}"
    if spec.key == "aen2-sticky-regime":
        return f"Aen#2 · Sticky R{regime_timeframe}/S{timeframe}"
    return f"{spec.label} · {timeframe}"


def modifier_v3(key: str) -> ModifierSpecV3:
    return next(item for item in MODIFIERS_V3 if item.key == key)


@dataclass(frozen=True, slots=True)
class LegacyMigrationV3:
    strategy_key: str
    timeframe: str
    modifiers: tuple[str, ...] = ()


LEGACY_V2_TO_V3: dict[str, LegacyMigrationV3] = {
    "family-macd-v1": LegacyMigrationV3("macd", "30m"),
    "macd-a-v1": LegacyMigrationV3("macd", "Adaptiv"),
    "macd-norm-v1": LegacyMigrationV3("macd", "5m", ("normalize",)),
    "macd-norm-manager-v1": LegacyMigrationV3("macd", "5m", ("normalize", "reversal", "take-profit")),
    "family-price-macd-v1": LegacyMigrationV3("price-macd", "5m"),
    "price-stoch-half-parade-v1": LegacyMigrationV3("price-stoch", "5m"),
    "sfl-1m-v1": LegacyMigrationV3("sfl", "1m"),
    "sfl-2m-v1": LegacyMigrationV3("sfl", "2m"),
    "sfl-5m-v1": LegacyMigrationV3("sfl", "5m"),
    "sfl-10m-v1": LegacyMigrationV3("sfl", "10m"),
    "macd-1m-flip-control-shadow-v1": LegacyMigrationV3("macd", "1m"),
    "macd-2m-flip-control-shadow-v1": LegacyMigrationV3("macd", "2m"),
    "macd-5m-flip-control-shadow-v1": LegacyMigrationV3("macd", "5m"),
    "macd-15m-flip-control-shadow-v1": LegacyMigrationV3("macd", "15m"),
}


def migrate_legacy_strategy_v3(strategy_key: str) -> LegacyMigrationV3 | None:
    return LEGACY_V2_TO_V3.get(str(strategy_key))
