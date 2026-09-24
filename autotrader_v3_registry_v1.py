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
    StrategySpecV3("macd-a", "MACD-A", "Adaptiv MACD-grunnstrategi, porteres fra V2 med parity-test."),
    StrategySpecV3("price-macd", "Price + MACD", "Prisstruktur kombinert med MACD."),
    StrategySpecV3("price-stoch", "Price + Stoch", "Prisstruktur kombinert med Stochastic."),
    StrategySpecV3("macd-histogram", "MACD Histogram", "Histogramretning styrer target inventory direkte."),
)

MODIFIERS_V3 = (
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
