from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StrategySpecV3:
    key: str
    label: str
    description: str


@dataclass(frozen=True, slots=True)
class ModifierSpecV3:
    key: str
    label: str
    description: str
    configurable: bool = True


STRATEGIES_V3 = (
    StrategySpecV3("macd", "MACD", "Ren MACD-grunnstrategi."),
    StrategySpecV3("price-macd", "Price + MACD", "Prisstruktur kombinert med MACD."),
    StrategySpecV3("price-stoch", "Price + Stoch", "Prisstruktur kombinert med Stochastic."),
    StrategySpecV3("sfl", "SFL", "State/flow/latency-grunnstrategi; periode velges separat."),
    StrategySpecV3("macd-histogram", "MACD Histogram", "Histogramretning styrer target inventory direkte."),
)

MODIFIERS_V3 = (
    ModifierSpecV3("normalize", "Normalization", "Normaliserer signalstyrke på tvers av valgte tidsvinduer."),
    ModifierSpecV3("mtf-confirmation", "MTF Confirmation", "Bruker høyere/lavere tidsperioder som kontekst uten å endre grunnstrategiens identitet."),
    ModifierSpecV3("impulse", "Impulse Detector", "Forsterker eller demper target ved endring i momentum."),
    ModifierSpecV3("reversal", "Reversal Detector", "Reduserer eller reverserer target ved bekreftet regimeskifte."),
    ModifierSpecV3("take-profit", "Take Profit", "Beskytter opparbeidet gevinst og kan sende target mot FLAT."),
    ModifierSpecV3("whipsaw", "Whipsaw Detector", "Demper handel i hakkete/retningsløse perioder."),
    ModifierSpecV3("regime", "Regime Detector", "Klassifiserer markedsregime for adaptive valg."),
)

TIMEFRAMES_V3 = ("1m", "2m", "5m", "10m", "15m", "30m", "1h", "Adaptiv")
CONTROL_MODES_V3 = ("Manuell", "Sim-Adapt", "Overseer", "God Mode")


def strategy_v3(key: str) -> StrategySpecV3:
    return next(item for item in STRATEGIES_V3 if item.key == key)


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
