from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from trading_desk import ChartBar
from trading_desk_indicators import TechnicalIndicators, calculate_indicators


AUTOTRADER_MODE_MANUAL = "Manuell"
AUTOTRADER_MODE_MACD_30M = "MACD 30m · prøve"
AUTOTRADER_MODES = (AUTOTRADER_MODE_MANUAL, AUTOTRADER_MODE_MACD_30M)
MACD_TIMEFRAME = "30m"


@dataclass(frozen=True, slots=True)
class MacdCrossoverIntent:
    """Execution-agnostic position intent from one closed 30m MACD crossover."""

    market: str
    bar_time: object
    side: str
    amount: float
    macd: float
    signal: float
    previous_delta: float
    current_delta: float
    event_key: str

    @property
    def direction(self) -> str:
        return "BULLISH" if self.side == "Buy" else "BEARISH"


def _aligned_macd_points(indicators: TechnicalIndicators) -> tuple[tuple[object, float, float], ...]:
    macd_by_time = {point.bar_time: float(point.value) for point in indicators.macd}
    signal_by_time = {point.bar_time: float(point.value) for point in indicators.macd_signal}
    common = sorted(set(macd_by_time) & set(signal_by_time))
    return tuple((stamp, macd_by_time[stamp], signal_by_time[stamp]) for stamp in common)


def crossover_from_indicators(
    indicators: TechnicalIndicators,
    *,
    market: str,
    amount: float,
) -> MacdCrossoverIntent | None:
    """Return an intent only when the latest two aligned MACD points cross.

    Bullish: MACD moves from at/below signal to above signal.
    Bearish: MACD moves from at/above signal to below signal.
    Staying on one side creates no repeated intent.
    """

    normalized_amount = float(amount)
    if normalized_amount <= 0:
        raise ValueError("amount must be positive")

    points = _aligned_macd_points(indicators)
    if len(points) < 2:
        return None

    _, previous_macd, previous_signal = points[-2]
    bar_time, current_macd, current_signal = points[-1]
    previous_delta = previous_macd - previous_signal
    current_delta = current_macd - current_signal

    side: str | None = None
    if previous_delta <= 0.0 < current_delta:
        side = "Buy"
    elif previous_delta >= 0.0 > current_delta:
        side = "Sell"
    if side is None:
        return None

    identity = f"macd30m|{market}|{bar_time}|{side}"
    event_key = sha256(identity.encode("utf-8")).hexdigest()[:24]
    return MacdCrossoverIntent(
        market=str(market),
        bar_time=bar_time,
        side=side,
        amount=normalized_amount,
        macd=current_macd,
        signal=current_signal,
        previous_delta=previous_delta,
        current_delta=current_delta,
        event_key=event_key,
    )


def latest_macd_crossover_intent(
    bars_30m: tuple[ChartBar, ...],
    *,
    market: str,
    amount: float,
) -> MacdCrossoverIntent | None:
    """Calculate the existing TradingDesk MACD and expose only the latest crossover."""

    if not bars_30m:
        return None
    indicators = calculate_indicators(bars_30m)
    return crossover_from_indicators(indicators, market=market, amount=amount)
