from __future__ import annotations

import numpy as np
import pandas as pd

from technical_core_v2 import build_baseline_forecast, build_technical_core_state


def _frame(periods: int, *, ascending: bool) -> pd.DataFrame:
    timestamps = pd.date_range("2026-08-01T10:00:00Z", periods=periods, freq="5min")
    direction = 1.0 if ascending else -1.0
    base = 100.0 + direction * np.linspace(0.0, 9.0, periods)
    wave = np.sin(np.linspace(0.0, 8.0 * np.pi, periods)) * 0.22
    close = base + wave
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": close - direction * 0.03,
            "high": close + 0.16,
            "low": close - 0.16,
            "close": close,
            "volume": np.linspace(100.0, 180.0, periods),
        }
    )


def test_same_input_produces_identical_state_and_forecast():
    frames = {"5m": _frame(120, ascending=True), "30m": _frame(100, ascending=True), "1h": _frame(90, ascending=True)}

    first = build_technical_core_state(frames, market="Silver")
    second = build_technical_core_state(frames, market="Silver")
    assert first == second

    forecast_a = build_baseline_forecast(first, horizon_seconds=3600)
    forecast_b = build_baseline_forecast(second, horizon_seconds=3600)
    assert forecast_a == forecast_b


def test_rising_market_is_bullish_and_falling_market_is_bearish():
    rising = build_technical_core_state({"30m": _frame(120, ascending=True)}, market="Gold")
    falling = build_technical_core_state({"30m": _frame(120, ascending=False)}, market="Gold")

    assert rising.score > 0
    assert rising.trend_state == "BULLISH"
    assert falling.score < 0
    assert falling.trend_state == "BEARISH"


def test_baseline_forecast_preserves_direction_and_bounds():
    state = build_technical_core_state({"30m": _frame(120, ascending=True)}, market="Brent")
    forecast = build_baseline_forecast(state, horizon_seconds=4 * 3600)

    assert forecast.direction == "BULLISH"
    assert forecast.expected_return > 0
    assert forecast.lower_return < forecast.expected_return < forecast.upper_return
    assert forecast.path_shape in {"DRIFT", "TREND_CONTINUATION"}


def test_primary_timeframe_prefers_30m_when_available():
    state = build_technical_core_state(
        {"5m": _frame(120, ascending=True), "30m": _frame(120, ascending=True), "1h": _frame(120, ascending=True)},
        market="DXY",
    )
    assert state.primary_timeframe == "30m"


def test_empty_input_is_rejected():
    try:
        build_technical_core_state({}, market="Silver")
    except ValueError as exc:
        assert "at least one" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_non_positive_horizon_is_rejected():
    state = build_technical_core_state({"30m": _frame(120, ascending=True)}, market="Silver")
    try:
        build_baseline_forecast(state, horizon_seconds=0)
    except ValueError as exc:
        assert "positive" in str(exc)
    else:
        raise AssertionError("Expected ValueError")
