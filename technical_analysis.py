from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True, slots=True)
class TechnicalReading:
    label: str
    interpretation: str
    indicator: str
    timeframe: str
    value: str
    bias: str

    def to_record(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def display(self) -> str:
        return f"{self.interpretation} ({self.indicator}, {self.timeframe}: {self.value})"


@dataclass(frozen=True, slots=True)
class TechnicalSnapshot:
    asset: str
    timeframe: str
    timestamp: str
    price: float
    rsi_14: float | None
    macd: float | None
    macd_signal: float | None
    macd_histogram: float | None
    ema_20: float | None
    ema_50: float | None
    atr_14: float | None
    atr_14_pct: float | None
    volume_ratio_20: float | None
    support: float | None
    resistance: float | None
    distance_to_support_pct: float | None
    distance_to_resistance_pct: float | None
    market_structure: str
    readings: tuple[TechnicalReading, ...]

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["readings"] = [item.to_record() for item in self.readings]
        return record


def _clean_frame(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"timestamp", "close"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Markedsdata mangler kolonner: {', '.join(sorted(missing))}")

    result = frame.copy()
    result["timestamp"] = pd.to_datetime(result["timestamp"], utc=True, errors="coerce")
    for column in ("open", "high", "low", "close", "volume"):
        if column in result:
            result[column] = pd.to_numeric(result[column], errors="coerce")
    result = result.dropna(subset=["timestamp", "close"]).sort_values("timestamp").drop_duplicates("timestamp")
    if result.empty:
        raise ValueError("Markedsdata inneholder ingen gyldige prisbarer")
    return result.reset_index(drop=True)


def _last(series: pd.Series) -> float | None:
    values = series.dropna()
    return float(values.iloc[-1]) if not values.empty else None


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gains = delta.clip(lower=0.0)
    losses = -delta.clip(upper=0.0)
    average_gain = gains.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    average_loss = losses.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    relative_strength = average_gain / average_loss.replace(0.0, np.nan)
    result = 100.0 - (100.0 / (1.0 + relative_strength))
    result = result.where(average_loss != 0.0, 100.0)
    return result.where(average_gain != 0.0, 0.0)


def _macd(close: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    fast = close.ewm(span=12, adjust=False, min_periods=12).mean()
    slow = close.ewm(span=26, adjust=False, min_periods=26).mean()
    line = fast - slow
    signal = line.ewm(span=9, adjust=False, min_periods=9).mean()
    return line, signal, line - signal


def _atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    if not {"high", "low"}.issubset(frame.columns):
        return pd.Series(index=frame.index, dtype=float)
    previous_close = frame["close"].shift(1)
    ranges = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    )
    true_range = ranges.max(axis=1)
    return true_range.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def _support_resistance(frame: pd.DataFrame, lookback: int = 48) -> tuple[float | None, float | None]:
    recent = frame.tail(max(lookback, 5))
    if recent.empty:
        return None, None
    low_source = recent["low"] if "low" in recent else recent["close"]
    high_source = recent["high"] if "high" in recent else recent["close"]
    return float(low_source.min()), float(high_source.max())


def _market_structure(frame: pd.DataFrame, pivot_window: int = 3) -> str:
    if not {"high", "low"}.issubset(frame.columns) or len(frame) < pivot_window * 2 + 5:
        return "UNDETERMINED"

    highs = frame["high"]
    lows = frame["low"]
    pivot_highs: list[float] = []
    pivot_lows: list[float] = []
    for index in range(pivot_window, len(frame) - pivot_window):
        high_window = highs.iloc[index - pivot_window : index + pivot_window + 1]
        low_window = lows.iloc[index - pivot_window : index + pivot_window + 1]
        current_high = float(highs.iloc[index])
        current_low = float(lows.iloc[index])
        if current_high == float(high_window.max()):
            pivot_highs.append(current_high)
        if current_low == float(low_window.min()):
            pivot_lows.append(current_low)

    if len(pivot_highs) < 2 or len(pivot_lows) < 2:
        return "UNDETERMINED"
    higher_high = pivot_highs[-1] > pivot_highs[-2]
    higher_low = pivot_lows[-1] > pivot_lows[-2]
    lower_high = pivot_highs[-1] < pivot_highs[-2]
    lower_low = pivot_lows[-1] < pivot_lows[-2]
    if higher_high and higher_low:
        return "HH_HL"
    if lower_high and lower_low:
        return "LH_LL"
    return "MIXED"


def _fmt(value: float | None, decimals: int = 3, suffix: str = "") -> str:
    if value is None:
        return "mangler"
    return f"{value:.{decimals}f}{suffix}"


def _build_readings(snapshot: dict[str, Any]) -> tuple[TechnicalReading, ...]:
    timeframe = str(snapshot["timeframe"])
    readings: list[TechnicalReading] = []

    rsi = snapshot["rsi_14"]
    if rsi is not None:
        if rsi >= 70:
            interpretation, bias = "Overkjøpt momentum", "bearish"
        elif rsi >= 60:
            interpretation, bias = "Sterkt, men høyt momentum", "bullish"
        elif rsi <= 30:
            interpretation, bias = "Oversolgt momentum", "bullish"
        elif rsi <= 40:
            interpretation, bias = "Svakt momentum", "bearish"
        else:
            interpretation, bias = "Nøytralt momentum", "neutral"
        readings.append(TechnicalReading("momentum", interpretation, "RSI 14", timeframe, _fmt(rsi, 1), bias))

    histogram = snapshot["macd_histogram"]
    macd = snapshot["macd"]
    signal = snapshot["macd_signal"]
    if histogram is not None and macd is not None and signal is not None:
        interpretation = "Positivt momentum" if histogram > 0 else "Negativt momentum" if histogram < 0 else "Flatt momentum"
        bias = "bullish" if histogram > 0 else "bearish" if histogram < 0 else "neutral"
        readings.append(
            TechnicalReading(
                "momentum",
                interpretation,
                "MACD 12/26/9",
                timeframe,
                f"histogram {histogram:+.4f}",
                bias,
            )
        )

    ema_20 = snapshot["ema_20"]
    ema_50 = snapshot["ema_50"]
    if ema_20 is not None and ema_50 is not None:
        interpretation = "Bullish trend" if ema_20 > ema_50 else "Bearish trend" if ema_20 < ema_50 else "Flat trend"
        bias = "bullish" if ema_20 > ema_50 else "bearish" if ema_20 < ema_50 else "neutral"
        readings.append(
            TechnicalReading(
                "trend",
                interpretation,
                "EMA 20/50",
                timeframe,
                f"{ema_20:.3f} / {ema_50:.3f}",
                bias,
            )
        )

    structure = snapshot["market_structure"]
    structure_text = {"HH_HL": "Bullish markedsstruktur", "LH_LL": "Bearish markedsstruktur", "MIXED": "Blandet markedsstruktur"}.get(structure)
    if structure_text:
        bias = "bullish" if structure == "HH_HL" else "bearish" if structure == "LH_LL" else "neutral"
        readings.append(TechnicalReading("structure", structure_text, "svingstruktur", timeframe, structure, bias))

    resistance_distance = snapshot["distance_to_resistance_pct"]
    if resistance_distance is not None:
        if resistance_distance <= 0.5:
            text, bias = "Svært nær lokal motstand", "bearish"
        elif resistance_distance <= 1.5:
            text, bias = "Nær lokal motstand", "neutral"
        else:
            text, bias = "God avstand til lokal motstand", "bullish"
        readings.append(TechnicalReading("level", text, "lokal motstand", timeframe, _fmt(resistance_distance, 2, " % unna"), bias))

    support_distance = snapshot["distance_to_support_pct"]
    if support_distance is not None:
        if support_distance <= 0.5:
            text, bias = "Svært nær lokal støtte", "bullish"
        elif support_distance <= 1.5:
            text, bias = "Nær lokal støtte", "neutral"
        else:
            text, bias = "Langt over lokal støtte", "bearish"
        readings.append(TechnicalReading("level", text, "lokal støtte", timeframe, _fmt(support_distance, 2, " % unna"), bias))

    atr_pct = snapshot["atr_14_pct"]
    if atr_pct is not None:
        readings.append(
            TechnicalReading(
                "volatility",
                "Aktuell intrabar-volatilitet",
                "ATR 14",
                timeframe,
                _fmt(atr_pct, 2, " % av pris"),
                "neutral",
            )
        )

    volume_ratio = snapshot["volume_ratio_20"]
    if volume_ratio is not None:
        if volume_ratio >= 1.5:
            text = "Sterk markedsdeltakelse"
        elif volume_ratio <= 0.65:
            text = "Svak markedsdeltakelse"
        else:
            text = "Normalt volum"
        readings.append(TechnicalReading("volume", text, "volumratio 20", timeframe, _fmt(volume_ratio, 2, "×"), "neutral"))

    return tuple(readings)


def build_technical_snapshot(frame: pd.DataFrame, *, asset: str, timeframe: str) -> TechnicalSnapshot:
    data = _clean_frame(frame)
    close = data["close"]
    price = float(close.iloc[-1])
    rsi = _last(_rsi(close))
    macd_line, macd_signal, macd_histogram = _macd(close)
    ema_20 = _last(close.ewm(span=20, adjust=False, min_periods=20).mean())
    ema_50 = _last(close.ewm(span=50, adjust=False, min_periods=50).mean())
    atr = _last(_atr(data))
    atr_pct = (atr / price * 100.0) if atr is not None and price else None

    volume_ratio = None
    if "volume" in data:
        rolling_volume = data["volume"].rolling(20, min_periods=5).median()
        baseline = _last(rolling_volume)
        current_volume = _last(data["volume"])
        if baseline and current_volume is not None:
            volume_ratio = current_volume / baseline

    support, resistance = _support_resistance(data)
    distance_to_support = ((price / support) - 1.0) * 100.0 if support and support > 0 else None
    distance_to_resistance = ((resistance / price) - 1.0) * 100.0 if resistance and price > 0 else None
    values: dict[str, Any] = {
        "asset": asset,
        "timeframe": timeframe,
        "timestamp": data.iloc[-1]["timestamp"].isoformat(),
        "price": price,
        "rsi_14": rsi,
        "macd": _last(macd_line),
        "macd_signal": _last(macd_signal),
        "macd_histogram": _last(macd_histogram),
        "ema_20": ema_20,
        "ema_50": ema_50,
        "atr_14": atr,
        "atr_14_pct": atr_pct,
        "volume_ratio_20": volume_ratio,
        "support": support,
        "resistance": resistance,
        "distance_to_support_pct": distance_to_support,
        "distance_to_resistance_pct": distance_to_resistance,
        "market_structure": _market_structure(data),
    }
    values["readings"] = _build_readings(values)
    return TechnicalSnapshot(**values)


def build_multi_timeframe_snapshot(
    frames: dict[str, pd.DataFrame],
    *,
    asset: str,
) -> dict[str, TechnicalSnapshot]:
    return {
        timeframe: build_technical_snapshot(frame, asset=asset, timeframe=timeframe)
        for timeframe, frame in frames.items()
        if frame is not None and not frame.empty
    }
