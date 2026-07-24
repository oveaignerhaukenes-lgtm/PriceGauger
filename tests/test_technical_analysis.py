from __future__ import annotations

import numpy as np
import pandas as pd

from technical_analysis import build_multi_timeframe_snapshot, build_technical_snapshot


def _trend_frame(periods: int = 120, *, ascending: bool = True) -> pd.DataFrame:
    timestamps = pd.date_range("2026-07-23T12:00:00Z", periods=periods, freq="5min")
    direction = 1.0 if ascending else -1.0
    base = 50.0 + direction * np.linspace(0.0, 8.0, periods)
    wave = np.sin(np.linspace(0.0, 10.0 * np.pi, periods)) * 0.35
    close = base + wave
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": close - direction * 0.04,
            "high": close + 0.18,
            "low": close - 0.18,
            "close": close,
            "volume": np.linspace(100.0, 220.0, periods),
        }
    )


def test_snapshot_calculates_standard_indicators():
    snapshot = build_technical_snapshot(_trend_frame(), asset="Silver", timeframe="5m")

    assert snapshot.asset == "Silver"
    assert snapshot.price > 50.0
    assert snapshot.rsi_14 is not None
    assert snapshot.macd is not None
    assert snapshot.macd_signal is not None
    assert snapshot.macd_histogram is not None
    assert snapshot.ema_20 is not None
    assert snapshot.ema_50 is not None
    assert snapshot.ema_20 > snapshot.ema_50
    assert snapshot.atr_14_pct is not None
    assert snapshot.support is not None
    assert snapshot.resistance is not None


def test_readings_expose_indicator_timeframe_and_value_in_parentheses():
    snapshot = build_technical_snapshot(_trend_frame(), asset="Brent", timeframe="30m")
    displays = [reading.display for reading in snapshot.readings]

    assert any("(RSI 14, 30m:" in item for item in displays)
    assert any("(MACD 12/26/9, 30m:" in item for item in displays)
    assert any("(EMA 20/50, 30m:" in item for item in displays)
    assert any("(ATR 14, 30m:" in item for item in displays)
    assert any("(volumratio 20, 30m:" in item for item in displays)


def test_falling_market_has_bearish_ema_reading():
    snapshot = build_technical_snapshot(_trend_frame(ascending=False), asset="Gold", timeframe="1h")
    ema_reading = next(item for item in snapshot.readings if item.indicator == "EMA 20/50")

    assert snapshot.ema_20 < snapshot.ema_50
    assert ema_reading.bias == "bearish"
    assert ema_reading.interpretation == "Bearish trend"


def test_multi_timeframe_snapshot_keeps_each_timeframe_separate():
    snapshots = build_multi_timeframe_snapshot(
        {
            "5m": _trend_frame(),
            "30m": _trend_frame(90),
            "1h": _trend_frame(70),
        },
        asset="DXY",
    )

    assert set(snapshots) == {"5m", "30m", "1h"}
    assert snapshots["5m"].timeframe == "5m"
    assert snapshots["1h"].asset == "DXY"


def test_missing_optional_ohlcv_columns_degrades_gracefully():
    frame = _trend_frame()[["timestamp", "close"]]
    snapshot = build_technical_snapshot(frame, asset="Silver", timeframe="5m")

    assert snapshot.rsi_14 is not None
    assert snapshot.atr_14 is None
    assert snapshot.volume_ratio_20 is None
    assert snapshot.market_structure == "UNDETERMINED"


def test_invalid_frame_is_rejected():
    frame = pd.DataFrame({"timestamp": ["2026-07-23T12:00:00Z"]})

    try:
        build_technical_snapshot(frame, asset="Brent", timeframe="5m")
    except ValueError as exc:
        assert "close" in str(exc)
    else:
        raise AssertionError("Expected ValueError")
