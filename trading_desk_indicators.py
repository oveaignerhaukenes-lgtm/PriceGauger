from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from collections.abc import Sequence

from trading_desk import ChartBar


INDICATOR_BOLLINGER = "Bollinger"
INDICATOR_MACD = "MACD"
INDICATOR_RSI = "RSI"
INDICATOR_OPTIONS = (INDICATOR_BOLLINGER, INDICATOR_MACD, INDICATOR_RSI)
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

    return TechnicalIndicators(
        bollinger_middle=_points(bars, middle),
        bollinger_upper=_points(bars, upper),
        bollinger_lower=_points(bars, lower),
        macd=_points(bars, macd_values),
        macd_signal=_points(bars, signal_values),
        macd_histogram=_points(bars, histogram),
        rsi=_points(bars, rsi_values),
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
    )
