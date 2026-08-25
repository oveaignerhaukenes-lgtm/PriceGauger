from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from collections.abc import Sequence

from trading_desk import ChartBar


INDICATOR_BOLLINGER = "Bollinger"
INDICATOR_MACD = "MACD"
INDICATOR_RSI = "RSI"
INDICATOR_EMA20 = "EMA 20"
INDICATOR_EMA50 = "EMA 50"
INDICATOR_SMA50 = "SMA 50"
INDICATOR_STOCHASTIC = "Stochastic"
INDICATOR_ATR = "ATR"
INDICATOR_SWING_BANDS = "Swing high/low"
INDICATOR_OPTIONS = (
    INDICATOR_BOLLINGER,
    INDICATOR_MACD,
    INDICATOR_RSI,
    INDICATOR_EMA20,
    INDICATOR_EMA50,
    INDICATOR_SMA50,
    INDICATOR_STOCHASTIC,
    INDICATOR_ATR,
    INDICATOR_SWING_BANDS,
)
DEFAULT_INDICATORS = (INDICATOR_BOLLINGER, INDICATOR_MACD, INDICATOR_RSI)
INDICATOR_WARMUP_PERIODS = 120


@dataclass(frozen=True, slots=True)
class IndicatorPoint:
    bar_time: object
    value: float


@dataclass(frozen=True, slots=True)
class TechnicalIndicators:
    bollinger_middle: tuple[IndicatorPoint, ...] = ()
    bollinger_upper: tuple[IndicatorPoint, ...] = ()
    bollinger_lower: tuple[IndicatorPoint, ...] = ()
    macd: tuple[IndicatorPoint, ...] = ()
    macd_signal: tuple[IndicatorPoint, ...] = ()
    macd_histogram: tuple[IndicatorPoint, ...] = ()
    rsi: tuple[IndicatorPoint, ...] = ()
    ema20: tuple[IndicatorPoint, ...] = ()
    ema50: tuple[IndicatorPoint, ...] = ()
    sma50: tuple[IndicatorPoint, ...] = ()
    stochastic_k: tuple[IndicatorPoint, ...] = ()
    stochastic_d: tuple[IndicatorPoint, ...] = ()
    atr: tuple[IndicatorPoint, ...] = ()


def _sma(values: Sequence[float], period: int) -> list[float | None]:
    if period <= 0:
        raise ValueError("period must be positive")
    result: list[float | None] = [None] * len(values)
    if len(values) < period:
        return result
    running = sum(values[:period])
    result[period - 1] = running / period
    for index in range(period, len(values)):
        running += values[index] - values[index - period]
        result[index] = running / period
    return result


def _ema(values: Sequence[float], period: int) -> list[float | None]:
    if period <= 0:
        raise ValueError("period must be positive")
    result: list[float | None] = [None] * len(values)
    if len(values) < period:
        return result
    current = sum(values[:period]) / period
    result[period - 1] = current
    alpha = 2.0 / (period + 1.0)
    for index in range(period, len(values)):
        current = alpha * values[index] + (1.0 - alpha) * current
        result[index] = current
    return result


def _points(bars: Sequence[ChartBar], values: Sequence[float | None]) -> tuple[IndicatorPoint, ...]:
    return tuple(
        IndicatorPoint(bar_time=bar.bar_time, value=float(value))
        for bar, value in zip(bars, values)
        if value is not None
    )


def _stochastic(
    bars: Sequence[ChartBar],
    *,
    period: int = 14,
    signal_period: int = 3,
) -> tuple[list[float | None], list[float | None]]:
    k_values: list[float | None] = [None] * len(bars)
    for index in range(period - 1, len(bars)):
        window = bars[index - period + 1 : index + 1]
        highest = max(float(item.high) for item in window)
        lowest = min(float(item.low) for item in window)
        spread = highest - lowest
        k_values[index] = 50.0 if spread == 0.0 else 100.0 * (float(bars[index].close) - lowest) / spread

    d_values: list[float | None] = [None] * len(bars)
    valid_indexes = [index for index, value in enumerate(k_values) if value is not None]
    compact = [float(k_values[index]) for index in valid_indexes]
    compact_signal = _sma(compact, signal_period)
    for compact_index, original_index in enumerate(valid_indexes):
        d_values[original_index] = compact_signal[compact_index]
    return k_values, d_values


def _atr(bars: Sequence[ChartBar], *, period: int = 14) -> list[float | None]:
    result: list[float | None] = [None] * len(bars)
    if len(bars) <= period:
        return result

    true_ranges: list[float] = []
    for index in range(1, len(bars)):
        current = bars[index]
        previous_close = float(bars[index - 1].close)
        high = float(current.high)
        low = float(current.low)
        true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))

    current_atr = sum(true_ranges[:period]) / period
    result[period] = current_atr
    for index in range(period + 1, len(bars)):
        current_atr = ((current_atr * (period - 1)) + true_ranges[index - 1]) / period
        result[index] = current_atr
    return result


def calculate_indicators(
    bars: Sequence[ChartBar],
    *,
    bollinger_period: int = 20,
    bollinger_stddev: float = 2.0,
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal: int = 9,
    rsi_period: int = 14,
) -> TechnicalIndicators:
    if not bars:
        return TechnicalIndicators()
    if bollinger_period <= 0 or bollinger_stddev <= 0:
        raise ValueError("invalid Bollinger parameters")
    if macd_fast <= 0 or macd_slow <= 0 or macd_signal <= 0 or macd_fast >= macd_slow:
        raise ValueError("invalid MACD parameters")
    if rsi_period <= 0:
        raise ValueError("invalid RSI period")

    closes = [float(bar.close) for bar in bars]

    middle = _sma(closes, bollinger_period)
    upper: list[float | None] = [None] * len(closes)
    lower: list[float | None] = [None] * len(closes)
    for index in range(bollinger_period - 1, len(closes)):
        window = closes[index - bollinger_period + 1 : index + 1]
        mean = float(middle[index])
        variance = sum((value - mean) ** 2 for value in window) / bollinger_period
        deviation = sqrt(variance) * bollinger_stddev
        upper[index] = mean + deviation
        lower[index] = mean - deviation

    fast = _ema(closes, macd_fast)
    slow = _ema(closes, macd_slow)
    macd_values: list[float | None] = [
        None if fast_value is None or slow_value is None else fast_value - slow_value
        for fast_value, slow_value in zip(fast, slow)
    ]
    macd_indexes = [index for index, value in enumerate(macd_values) if value is not None]
    signal_values: list[float | None] = [None] * len(closes)
    if len(macd_indexes) >= macd_signal:
        compact = [float(macd_values[index]) for index in macd_indexes]
        compact_signal = _ema(compact, macd_signal)
        for compact_index, original_index in enumerate(macd_indexes):
            signal_values[original_index] = compact_signal[compact_index]
    histogram: list[float | None] = [
        None if macd_value is None or signal_value is None else macd_value - signal_value
        for macd_value, signal_value in zip(macd_values, signal_values)
    ]

    rsi_values: list[float | None] = [None] * len(closes)
    if len(closes) > rsi_period:
        gains: list[float] = []
        losses: list[float] = []
        for index in range(1, rsi_period + 1):
            change = closes[index] - closes[index - 1]
            gains.append(max(change, 0.0))
            losses.append(max(-change, 0.0))
        average_gain = sum(gains) / rsi_period
        average_loss = sum(losses) / rsi_period

        def rsi_value(gain: float, loss: float) -> float:
            if loss == 0.0:
                return 50.0 if gain == 0.0 else 100.0
            relative_strength = gain / loss
            return 100.0 - (100.0 / (1.0 + relative_strength))

        rsi_values[rsi_period] = rsi_value(average_gain, average_loss)
        for index in range(rsi_period + 1, len(closes)):
            change = closes[index] - closes[index - 1]
            gain = max(change, 0.0)
            loss = max(-change, 0.0)
            average_gain = ((average_gain * (rsi_period - 1)) + gain) / rsi_period
            average_loss = ((average_loss * (rsi_period - 1)) + loss) / rsi_period
            rsi_values[index] = rsi_value(average_gain, average_loss)

    stochastic_k, stochastic_d = _stochastic(bars)
    atr_values = _atr(bars)

    return TechnicalIndicators(
        bollinger_middle=_points(bars, middle),
        bollinger_upper=_points(bars, upper),
        bollinger_lower=_points(bars, lower),
        macd=_points(bars, macd_values),
        macd_signal=_points(bars, signal_values),
        macd_histogram=_points(bars, histogram),
        rsi=_points(bars, rsi_values),
        ema20=_points(bars, _ema(closes, 20)),
        ema50=_points(bars, _ema(closes, 50)),
        sma50=_points(bars, _sma(closes, 50)),
        stochastic_k=_points(bars, stochastic_k),
        stochastic_d=_points(bars, stochastic_d),
        atr=_points(bars, atr_values),
    )


def clip_indicators(
    indicators: TechnicalIndicators,
    *,
    start: object,
    end: object,
) -> TechnicalIndicators:
    def clip(points: tuple[IndicatorPoint, ...]) -> tuple[IndicatorPoint, ...]:
        return tuple(point for point in points if start <= point.bar_time <= end)

    return TechnicalIndicators(
        bollinger_middle=clip(indicators.bollinger_middle),
        bollinger_upper=clip(indicators.bollinger_upper),
        bollinger_lower=clip(indicators.bollinger_lower),
        macd=clip(indicators.macd),
        macd_signal=clip(indicators.macd_signal),
        macd_histogram=clip(indicators.macd_histogram),
        rsi=clip(indicators.rsi),
        ema20=clip(indicators.ema20),
        ema50=clip(indicators.ema50),
        sma50=clip(indicators.sma50),
        stochastic_k=clip(indicators.stochastic_k),
        stochastic_d=clip(indicators.stochastic_d),
        atr=clip(indicators.atr),
    )
