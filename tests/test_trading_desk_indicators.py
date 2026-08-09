from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from trading_desk import ChartBar
from trading_desk_chart import OVERLAY_NORMALIZED, build_trading_desk_figure
from trading_desk_indicators import (
    INDICATOR_BOLLINGER,
    INDICATOR_MACD,
    INDICATOR_RSI,
    calculate_indicators,
    clip_indicators,
)


def _bars(count: int, *, start: float = 1.0) -> tuple[ChartBar, ...]:
    origin = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)
    return tuple(
        ChartBar(
            market="Gold",
            bar_time=origin + timedelta(minutes=index * 5),
            open=start + index - 0.2,
            high=start + index + 0.4,
            low=start + index - 0.5,
            close=start + index,
            volume=100.0 + index,
        )
        for index in range(count)
    )


def test_standard_indicator_periods_and_values() -> None:
    bars = _bars(40)
    indicators = calculate_indicators(bars)

    assert indicators.bollinger_middle[0].bar_time == bars[19].bar_time
    assert indicators.bollinger_middle[-1].value == pytest.approx(30.5)
    assert indicators.bollinger_upper[-1].value > indicators.bollinger_middle[-1].value
    assert indicators.bollinger_lower[-1].value < indicators.bollinger_middle[-1].value

    assert indicators.macd[0].bar_time == bars[25].bar_time
    assert indicators.macd_signal[0].bar_time == bars[33].bar_time
    assert indicators.macd_histogram[0].bar_time == bars[33].bar_time
    assert indicators.macd[-1].value > 0

    assert indicators.rsi[0].bar_time == bars[14].bar_time
    assert indicators.rsi[-1].value == pytest.approx(100.0)


def test_flat_market_rsi_is_neutral() -> None:
    bars = tuple(
        ChartBar(
            market="Gold",
            bar_time=datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc) + timedelta(minutes=index),
            open=100,
            high=100,
            low=100,
            close=100,
            volume=None,
        )
        for index in range(20)
    )

    indicators = calculate_indicators(bars)
    assert indicators.rsi[-1].value == pytest.approx(50.0)


def test_indicator_clipping_keeps_only_visible_chart_range() -> None:
    bars = _bars(50)
    indicators = calculate_indicators(bars)
    clipped = clip_indicators(indicators, start=bars[40].bar_time, end=bars[45].bar_time)

    for points in (
        clipped.bollinger_middle,
        clipped.bollinger_upper,
        clipped.bollinger_lower,
        clipped.macd,
        clipped.macd_signal,
        clipped.macd_histogram,
        clipped.rsi,
    ):
        assert all(bars[40].bar_time <= point.bar_time <= bars[45].bar_time for point in points)


def test_chart_renders_bollinger_macd_and_rsi_on_owned_axes() -> None:
    bars = _bars(60)
    indicators = calculate_indicators(bars)

    fig = build_trading_desk_figure(
        market="Gold",
        timeframe="5m",
        window_hours=24,
        primary=bars,
        overlays={},
        overlay_mode=OVERLAY_NORMALIZED,
        indicators=indicators,
        indicator_names=(INDICATOR_BOLLINGER, INDICATOR_MACD, INDICATOR_RSI),
    )

    traces = {trace.name: trace for trace in fig.data}
    assert traces["Bollinger øvre (20,2)"].yaxis == "y"
    assert traces["Bollinger midt (20)"].yaxis == "y"
    assert traces["Bollinger nedre (20,2)"].yaxis == "y"
    assert traces["Gold · volum"].yaxis == "y3"
    assert traces["MACD (12,26)"].yaxis == "y4"
    assert traces["Signal (9)"].yaxis == "y4"
    assert traces["MACD histogram"].yaxis == "y4"
    assert traces["RSI (14)"].yaxis == "y5"
    assert fig.layout.yaxis4.title.text == "MACD"
    assert fig.layout.yaxis5.title.text == "RSI"
    assert list(fig.layout.yaxis5.range) == [0, 100]
    assert fig.layout.xaxis4.title.text == "Tid · UTC"


def test_chart_uses_two_axis_cursor_crosshair() -> None:
    bars = _bars(60)
    indicators = calculate_indicators(bars)
    fig = build_trading_desk_figure(
        market="Gold",
        timeframe="5m",
        window_hours=24,
        primary=bars,
        overlays={},
        overlay_mode=OVERLAY_NORMALIZED,
        indicators=indicators,
        indicator_names=(INDICATOR_MACD, INDICATOR_RSI),
    )

    assert fig.layout.hovermode == "closest"
    assert fig.layout.xaxis.showspikes is True
    assert fig.layout.xaxis.spikesnap == "cursor"
    assert "across" in fig.layout.xaxis.spikemode
    assert fig.layout.yaxis.showspikes is True
    assert fig.layout.yaxis.spikesnap == "cursor"
    assert "across" in fig.layout.yaxis.spikemode
    assert "toaxis" in fig.layout.yaxis.spikemode
    assert fig.layout.yaxis.hoverformat == ".4~g"
    assert fig.layout.yaxis4.showspikes is True
    assert fig.layout.yaxis5.showspikes is True


def test_indicator_lines_are_visually_subordinate_to_candles() -> None:
    bars = _bars(60)
    indicators = calculate_indicators(bars)
    fig = build_trading_desk_figure(
        market="Gold",
        timeframe="5m",
        window_hours=24,
        primary=bars,
        overlays={},
        overlay_mode=OVERLAY_NORMALIZED,
        indicators=indicators,
        indicator_names=(INDICATOR_BOLLINGER, INDICATOR_MACD, INDICATOR_RSI),
    )

    traces = {trace.name: trace for trace in fig.data}
    assert traces["Bollinger øvre (20,2)"].line.width < 1.0
    assert traces["Bollinger nedre (20,2)"].line.width < 1.0
    assert traces["Bollinger midt (20)"].opacity < 1.0
    assert traces["MACD (12,26)"].line.width <= 1.1
    assert traces["MACD (12,26)"].opacity < 1.0
    assert traces["Signal (9)"].opacity < 1.0
    assert traces["MACD histogram"].opacity < 1.0
    assert traces["RSI (14)"].line.width <= 1.1
    assert traces["RSI (14)"].opacity < 1.0


def test_unknown_indicator_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported TradingDesk indicators"):
        build_trading_desk_figure(
            market="Gold",
            timeframe="5m",
            window_hours=24,
            primary=_bars(2),
            overlays={},
            overlay_mode=OVERLAY_NORMALIZED,
            indicator_names=("Stochastic",),
        )
